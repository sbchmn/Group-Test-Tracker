"""Discord bot runtime for Group Test Manager."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import IntegrityError

from . import create_app, db
from .models import (
    DiscordCommandInvocation,
    DiscordLinkToken,
    GroupTest,
    NotificationConfig,
    Participation,
    TelegramCommandTemplate,
    User,
)
from .notifications import append_notification_log, render_notification_template, send_discord_status_channel_message
from .public_results_bot import public_result_tag_page, public_results_for_tag_page

APP = create_app()


def _config_value(key, default=None):
    with APP.app_context():
        item = NotificationConfig.query.filter_by(key=key).first()
        if item is None:
            return default
        return item.value


def _builtin_enabled(command_name):
    return str(_config_value(f'builtin_{command_name}_enabled', 'true')).lower() == 'true'


def _normalize_command_name(command_name):
    command_name = str(command_name or "").strip().lower().lstrip("/")
    command_name = command_name.replace(" ", "-")
    command_name = re.sub(r"[^a-z0-9_-]", "", command_name)
    return command_name[:32]


def _discord_display_name(interaction):
    user = interaction.user
    display_name = getattr(user, "display_name", None) or getattr(user, "global_name", None)
    return str(display_name or getattr(user, "name", "")).strip() or "Discord user"


def _get_user_by_discord_id(discord_user_id):
    return User.query.filter_by(discord_user_id=str(discord_user_id)).first()


def _get_active_link_token(token_value):
    token = DiscordLinkToken.query.filter_by(token=token_value).first()
    if token is None:
        return None
    if token.used_at is not None or token.expires_at < datetime.utcnow():
        return None
    return token


def _claim_discord_link(token_value, discord_user_id, discord_username):
    """Atomically consume a link token without moving an existing account link."""
    token = (
        DiscordLinkToken.query
        .filter_by(token=str(token_value or "").strip())
        .with_for_update()
        .first()
    )
    if token is None or token.used_at is not None or token.expires_at < datetime.utcnow():
        return None, "invalid"

    discord_user_id = str(discord_user_id).strip()
    existing_owner = User.query.filter_by(discord_user_id=discord_user_id).first()
    if existing_owner is not None and existing_owner.id != token.user_id:
        return None, "discord-owned"

    user = db.session.get(User, token.user_id)
    if user is None:
        return None, "missing-user"
    if user.discord_user_id and str(user.discord_user_id) != discord_user_id:
        return None, "user-owned"

    user.discord_user_id = discord_user_id
    user.discord_username = discord_username
    token.used_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "conflict"
    return user, None


def _build_help_text():
    base_lines = [
        "Available Discord commands:",
        "/start <token> - link your Discord account",
        "/help - show this help",
        "/tests - list tests you can see",
        "/mytests - list your pending/approved/denied tests",
        "/status <test id> - check a test status",
        "/join <test id> - request to join a recruiting test",
    ]
    with APP.app_context():
        custom_commands = TelegramCommandTemplate.query.filter_by(is_active=True).filter(TelegramCommandTemplate.command != '/publicresults').order_by(TelegramCommandTemplate.command.asc()).all()
        if custom_commands:
            base_lines.append("")
            base_lines.append("Custom commands:")
            for template in custom_commands:
                base_lines.append(f"/{_normalize_command_name(template.command)} - {template.description or 'Custom reply'}")
    return "\n".join(base_lines)


async def _run_db(fn, *args, **kwargs):
    return await asyncio.to_thread(_run_db_sync, fn, *args, **kwargs)


def _run_db_sync(fn, *args, **kwargs):
    with APP.app_context():
        return fn(*args, **kwargs)


def _linked_user_response(discord_user_id, builder, *args):
    user = _get_user_by_discord_id(discord_user_id)
    if user is None:
        return "Your Discord account is not linked yet. Run /start <token> from your profile."
    return builder(user, *args)


def _link_discord_account(token_value, discord_user_id, discord_username):
    user, link_error = _claim_discord_link(token_value, discord_user_id, discord_username)
    if link_error == "invalid":
        return "That link token is invalid or expired. Generate a new token from your profile."
    if link_error == "discord-owned":
        return "This Discord account is already linked to a different user."
    if link_error == "user-owned":
        return "This Group Test Manager account is already linked to a different Discord account."
    if link_error in {"missing-user", "conflict"} or user is None:
        return "The linked user no longer exists or the link was claimed concurrently."
    return "Discord account linked successfully."


def _build_status_response(user, test_id):
    _, text = _build_status_text(user, test_id)
    return text


def _build_join_response(user, test_id):
    _, text = _request_join_test(user, test_id)
    return text


def _public_results_discord_page(tag_id=None, page=1):
    if tag_id is None:
        tags, page, total_pages = public_result_tag_page(page)
        if not tags:
            return 'No Public Results Available.', None, []
        return (
            f'Public Result Tags (page {page}/{total_pages}):',
            ('tags', page, total_pages),
            [(tag.id, tag.name) for tag in tags],
        )

    tag, results, page, total_pages = public_results_for_tag_page(tag_id, page)
    if tag is None or not results:
        return 'No Public Results Available.', ('empty',), []
    lines = [f'Public Results for {tag.name} (page {page}/{total_pages}):']
    for result in results:
        lines.append(f'- {result.title} ({result.created_at.strftime("%Y-%m-%d")})')
    return '\n'.join(lines), ('results', tag.id, page, total_pages), [
        (result.title, result.results_link) for result in results
    ]


def _run_discord_public_results(user_id, channel_id, guild_id):
    allowed, message = _discord_public_results_access(user_id, channel_id, guild_id)
    if not allowed:
        return message, None
    body, state, items = _public_results_discord_page()
    return body, (*state, items)


def _discord_public_results_access(user_id, channel_id, guild_id):
    enabled = str((NotificationConfig.query.filter_by(key='builtin_publicresults_enabled').first() or type('Config', (), {'value': 'true'})()).value).lower() == 'true'
    if not enabled:
        return False, 'This command is currently disabled.'
    allow_non_private = str((NotificationConfig.query.filter_by(key='builtin_publicresults_allow_non_private').first() or type('Config', (), {'value': 'false'})()).value).lower() == 'true'
    if guild_id is not None and not allow_non_private:
        return False, 'This command is limited to direct messages only.'
    allowed_chats = {entry.strip() for entry in str((NotificationConfig.query.filter_by(key='builtin_publicresults_allowed_chat_ids').first() or type('Config', (), {'value': ''})()).value or '').split(',') if entry.strip()}
    if allowed_chats and str(channel_id) not in allowed_chats and str(guild_id) not in allowed_chats:
        return False, 'This command is not enabled in this Discord server or channel.'
    allowed_threads = {entry.strip() for entry in str((NotificationConfig.query.filter_by(key='builtin_publicresults_allowed_thread_ids').first() or type('Config', (), {'value': ''})()).value or '').split(',') if entry.strip()}
    if allowed_threads:
        return False, 'This command is not enabled in this Discord thread.'
    if guild_id is None and _get_user_by_discord_id(user_id) is None:
        return False, 'Your Discord account is not linked yet. Run /start <token> from your profile.'
    return True, None


class PublicResultsView(discord.ui.View):
    def __init__(self, state, timeout=900):
        super().__init__(timeout=timeout)
        self.state = state
        self._build_buttons()

    def _build_buttons(self):
        if self.state[0] == 'tags':
            _, page, total_pages, items = self.state
            for tag_id, tag_name in items:
                button = discord.ui.Button(label=tag_name[:80], style=discord.ButtonStyle.secondary)
                button.callback = self._tag_callback(tag_id)
                self.add_item(button)
            if page > 1:
                button = discord.ui.Button(label='Previous', style=discord.ButtonStyle.primary)
                button.callback = self._tags_page_callback(page - 1)
                self.add_item(button)
            if page < total_pages:
                button = discord.ui.Button(label='Next', style=discord.ButtonStyle.primary)
                button.callback = self._tags_page_callback(page + 1)
                self.add_item(button)
            close = discord.ui.Button(label='Close', style=discord.ButtonStyle.danger)
            close.callback = self._close_callback()
            self.add_item(close)
            return

        _, tag_id, page, total_pages, items = self.state
        for title, result_link in items:
            self.add_item(discord.ui.Button(label=f'COA: {title}'[:80], style=discord.ButtonStyle.link, url=result_link))
        back = discord.ui.Button(label='Back to Tags', style=discord.ButtonStyle.secondary)
        back.callback = self._tags_page_callback(1)
        self.add_item(back)
        if page > 1:
            button = discord.ui.Button(label='Previous', style=discord.ButtonStyle.primary)
            button.callback = self._results_page_callback(tag_id, page - 1)
            self.add_item(button)
        if page < total_pages:
            button = discord.ui.Button(label='Next', style=discord.ButtonStyle.primary)
            button.callback = self._results_page_callback(tag_id, page + 1)
            self.add_item(button)
        close = discord.ui.Button(label='Close', style=discord.ButtonStyle.danger)
        close.callback = self._close_callback()
        self.add_item(close)

    def _render_callback(self, tag_id, page):
        async def callback(button_interaction):
            allowed, message = await _run_db(_discord_public_results_access, button_interaction.user.id, button_interaction.channel_id, button_interaction.guild_id)
            if not allowed:
                await button_interaction.response.send_message(message, ephemeral=True)
                return
            body, state, items = await _run_db(_public_results_discord_page, tag_id, page)
            await button_interaction.response.edit_message(content=body, view=PublicResultsView((*state, items) if state[0] in {'tags', 'results'} else state))
        return callback

    def _tag_callback(self, tag_id):
        return self._render_callback(tag_id, 1)

    def _tags_page_callback(self, page):
        return self._render_callback(None, page)

    def _results_page_callback(self, tag_id, page):
        return self._render_callback(tag_id, page)

    def _close_callback(self):
        async def callback(button_interaction):
            await button_interaction.response.defer()
            await button_interaction.delete_original_response()
        return callback


def _visible_tests_for_user(user):
    tests = GroupTest.query.order_by(GroupTest.id.asc()).all()
    if user.is_admin:
        return tests
    return [test for test in tests if test.can_user_see(user)]


def _participation_rows_for_user(user):
    return (
        db.session.query(Participation, GroupTest)
        .join(GroupTest, GroupTest.id == Participation.group_test_id)
        .filter(Participation.user_id == user.id)
        .order_by(GroupTest.id.asc())
        .all()
    )


def _format_test_line(test, user=None):
    status_label = str(test.status or "").replace("_", " ").title() or "Unknown"
    line = f"#{test.id} {test.title} - {status_label}"
    if user is not None:
        participation = Participation.query.filter_by(group_test_id=test.id, user_id=user.id).first()
        if participation is not None:
            if participation.approved:
                line += " - approved"
            elif participation.denied:
                line += " - denied"
            else:
                line += " - pending"
    return line


def _build_tests_text(user):
    tests = _visible_tests_for_user(user)
    if not tests:
        return "No visible tests right now."

    lines = ["Visible tests:"]
    for test in tests:
        lines.append(f"- {_format_test_line(test, user)}")
        if test.status == 'recruiting':
            lines.append(f"  /status {test.id}")
            lines.append(f"  /join {test.id}")
        else:
            lines.append(f"  /status {test.id}")
    return "\n".join(lines)


def _build_mytests_text(user):
    rows = _participation_rows_for_user(user)
    if not rows:
        return "You do not have any test requests yet."

    lines = ["Your test requests:"]
    for participation, test in rows:
        if participation.approved:
            state = 'approved'
        elif participation.denied:
            state = 'denied'
        else:
            state = 'pending'
        lines.append(f"- #{test.id} {test.title} - {state}")
        lines.append(f"  /status {test.id}")
        if state == 'approved' and test.status == 'recruiting':
            lines.append(f"  /join {test.id}")
    return "\n".join(lines)


def _build_status_text(user, test_id):
    test = GroupTest.query.get(test_id)
    if test is None:
        return None, "No test found for that id."
    if not test.can_user_see(user) and not user.is_admin:
        participation = Participation.query.filter_by(group_test_id=test.id, user_id=user.id).first()
        if participation is None:
            return None, "You do not have access to that test."

    participation = Participation.query.filter_by(group_test_id=test.id, user_id=user.id).first()
    status_label = str(test.status or "").replace("_", " ").title() or "Unknown"
    lines = [f"#{test.id} {test.title}", f"Status: {status_label}"]
    if participation is not None:
        if participation.approved:
            lines.append("Your participation: approved")
        elif participation.denied:
            lines.append(f"Your participation: denied{f' ({participation.denied_reason})' if participation.denied_reason else ''}")
        else:
            lines.append("Your participation: pending")
    elif test.status == 'recruiting':
        lines.append("You can request to join this test.")
    return test, "\n".join(lines)


def _request_join_test(user, test_id):
    test = GroupTest.query.get(test_id)
    if test is None:
        return None, "No test found for that id."
    if test.status != 'recruiting':
        return None, "This test is not accepting new requests right now."
    if not test.can_user_see(user):
        return None, "You are not allowed to see this test."

    existing = Participation.query.filter_by(group_test_id=test.id, user_id=user.id).first()
    if existing is not None:
        if existing.approved:
            return test, "You are already approved for this test."
        if existing.denied:
            return test, "This request was denied. Contact an admin if you need it reopened."
        return test, "You already have a pending request for this test."

    participation = Participation(
        group_test_id=test.id,
        user_id=user.id,
        name=user.username,
        tg_username=user.tg_username,
        us_based=True,
        state=None,
        vial_donor=False,
        notes='Requested from Discord',
        denied=False,
        denied_at=None,
        denied_reason=None,
        approved=False,
    )
    db.session.add(participation)
    db.session.commit()
    return test, "Your request was submitted successfully."


def _check_custom_command_scope(template, interaction):
    channel_id = str(interaction.channel_id or "").strip()
    guild_id = str(interaction.guild_id or "").strip()
    if interaction.guild_id is not None and not template.allow_non_private:
        return False, "This command is limited to direct messages only."

    allowed_chat_ids = {entry.strip() for entry in str(template.allowed_chat_ids or "").split(',') if entry.strip()}
    allowed_thread_ids = {entry.strip() for entry in str(template.allowed_thread_ids or "").split(',') if entry.strip()}
    if allowed_chat_ids and channel_id not in allowed_chat_ids and guild_id not in allowed_chat_ids:
        return False, "This command is not enabled in this Discord channel or server."
    if allowed_thread_ids and channel_id not in allowed_thread_ids:
        return False, "This command is not enabled in this Discord thread."
    return True, None


def _check_custom_command_args(template, args_text):
    args_text = str(args_text or "").strip()
    policy = str(template.args_policy or 'any').strip().lower()
    if policy == 'none' and args_text:
        return False, 'This command does not accept arguments.'
    if policy == 'required' and not args_text:
        return False, 'This command requires arguments.'
    if policy == 'regex':
        regex = str(template.args_regex or '').strip()
        if not regex:
            return True, None
        try:
            if not re.fullmatch(regex, args_text):
                return False, template.args_help_text or 'The provided arguments do not match the required format.'
        except re.error:
            return False, 'This command has an invalid argument pattern.'
    return True, None


def _custom_command_rate_limited(template, channel_id):
    window_seconds = template.rate_limit_window_seconds
    max_calls = template.rate_limit_max_calls
    if not window_seconds or not max_calls:
        return False

    threshold = datetime.utcnow() - timedelta(seconds=int(window_seconds))
    call_count = (
        DiscordCommandInvocation.query
        .filter(
            DiscordCommandInvocation.command_template_id == template.id,
            DiscordCommandInvocation.channel_id == str(channel_id),
            DiscordCommandInvocation.created_at >= threshold,
        )
        .count()
    )
    return call_count >= int(max_calls)


def _record_custom_command_invocation(template, channel_id):
    db.session.add(DiscordCommandInvocation(command_template_id=template.id, channel_id=str(channel_id)))
    db.session.commit()


def _render_custom_command_reply(template, interaction, args_text):
    user = interaction.user
    context = {
        'username': _discord_display_name(interaction),
        'discord_username': _discord_display_name(interaction),
        'discord_user_id': str(user.id),
        'args': args_text,
        'command': _normalize_command_name(template.command),
        'display_name': _discord_display_name(interaction),
    }
    return render_notification_template(template.reply_text, context)


def _run_dynamic_command(template_id, discord_user_id, display_name, channel_id, guild_id, args_text):
    template = db.session.get(TelegramCommandTemplate, template_id)
    if template is None or not template.is_active:
        return "This command is no longer active."

    user = _get_user_by_discord_id(discord_user_id)
    if user is None:
        return "Your Discord account is not linked yet. Run /start <token> from your profile."

    class CommandInteraction:
        def __init__(self):
            self.channel_id = channel_id
            self.guild_id = guild_id
            self.user = type("DiscordCommandUser", (), {
                "id": discord_user_id,
                "display_name": display_name,
                "global_name": display_name,
                "name": display_name,
            })()

    command_interaction = CommandInteraction()
    allowed, scope_message = _check_custom_command_scope(template, command_interaction)
    if not allowed:
        return scope_message

    args_ok, args_message = _check_custom_command_args(template, args_text)
    if not args_ok:
        return args_message

    if _custom_command_rate_limited(template, channel_id):
        return template.rate_limit_message or 'This command is temporarily rate limited.'

    reply_text = _render_custom_command_reply(template, command_interaction, args_text)
    _record_custom_command_invocation(template, channel_id)
    return reply_text or "Command completed without a configured response."


class DiscordBot(commands.Bot):
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        append_notification_log(f"discord: application command failed: {type(error).__name__}")
        message = "Discord could not complete that command. Please try again shortly."
        if interaction.response.is_done():
            await interaction.edit_original_response(content=message)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def setup_hook(self):
        self._register_static_commands()
        self._register_dynamic_commands()
        await self._sync_commands()

    def _register_static_commands(self):
        @self.tree.command(name="help", description="Show available commands")
        async def help_command(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            text = await _run_db(_build_help_text)
            await interaction.edit_original_response(content=text)

        @self.tree.command(name="start", description="Link this Discord account with Group Test Manager")
        @app_commands.describe(token="Link token from your profile page")
        async def start_command(interaction: discord.Interaction, token: str | None = None):
            token_value = str(token or "").strip()
            if not token_value:
                await interaction.response.send_message(
                    "Open your Group Test Manager profile, generate a Discord link token, then run /start <token>.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(ephemeral=True)
            text = await _run_db(
                _link_discord_account,
                token_value,
                interaction.user.id,
                _discord_display_name(interaction),
            )
            await interaction.edit_original_response(content=text)

        @self.tree.command(name="tests", description="List visible tests")
        async def tests_command(interaction: discord.Interaction):
            if not await _run_db(_builtin_enabled, 'tests'):
                await interaction.response.send_message('This command is currently disabled.', ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            text = await _run_db(
                _linked_user_response,
                interaction.user.id,
                _build_tests_text,
            )
            await interaction.edit_original_response(content=text)

        @self.tree.command(name="mytests", description="List your participation requests")
        async def mytests_command(interaction: discord.Interaction):
            if not await _run_db(_builtin_enabled, 'mytests'):
                await interaction.response.send_message('This command is currently disabled.', ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            text = await _run_db(
                _linked_user_response,
                interaction.user.id,
                _build_mytests_text,
            )
            await interaction.edit_original_response(content=text)

        @self.tree.command(name="status", description="Check a test status")
        @app_commands.describe(test_id="Test ID")
        async def status_command(interaction: discord.Interaction, test_id: int):
            if not await _run_db(_builtin_enabled, 'status'):
                await interaction.response.send_message('This command is currently disabled.', ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            text = await _run_db(
                _linked_user_response,
                interaction.user.id,
                _build_status_response,
                test_id,
            )
            await interaction.edit_original_response(content=text)

        @self.tree.command(name="join", description="Request to join a recruiting test")
        @app_commands.describe(test_id="Test ID")
        async def join_command(interaction: discord.Interaction, test_id: int):
            if not await _run_db(_builtin_enabled, 'join'):
                await interaction.response.send_message('This command is currently disabled.', ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            text = await _run_db(
                _linked_user_response,
                interaction.user.id,
                _build_join_response,
                test_id,
            )
            await interaction.edit_original_response(content=text)

        @self.tree.command(name="publicresults", description="Browse public result tags and COA links")
        async def publicresults_command(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            text, view_state = await _run_db(
                _run_discord_public_results,
                interaction.user.id,
                interaction.channel_id,
                interaction.guild_id,
            )
            view = PublicResultsView(view_state) if view_state else None
            await interaction.edit_original_response(content=text, view=view)

    def _register_dynamic_commands(self):
        with APP.app_context():
            templates = TelegramCommandTemplate.query.filter_by(is_active=True).order_by(TelegramCommandTemplate.command.asc()).all()

        reserved_names = {"help", "start", "tests", "mytests", "status", "join", "publicresults"}

        for template in templates:
            command_name = _normalize_command_name(template.command)
            if not command_name or command_name in reserved_names:
                append_notification_log(f"discord: skipped dynamic command collision or invalid name: {template.command}", debug=True)
                continue

            def _make_dynamic_command(template):
                async def dynamic_command(interaction: discord.Interaction, args: str | None = None):
                    await interaction.response.defer(ephemeral=True)
                    text = await _run_db(
                        _run_dynamic_command,
                        template.id,
                        interaction.user.id,
                        _discord_display_name(interaction),
                        interaction.channel_id,
                        interaction.guild_id,
                        str(args or "").strip(),
                    )
                    await interaction.edit_original_response(content=text)

                return dynamic_command

            description = (template.description or template.reply_text or 'Custom command').strip()[:100]
            self.tree.add_command(
                app_commands.Command(
                    name=command_name,
                    description=description or 'Custom command',
                    callback=_make_dynamic_command(template),
                )
            )

    async def _sync_commands(self):
        guild_id = str(_config_value('discord_guild_id') or '').strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()


async def _run_bot():
    token = str(_config_value('discord_bot_token') or '').strip()
    if not token:
        append_notification_log('discord: bot token missing, bot process exiting')
        return

    intents = discord.Intents.default()
    bot = DiscordBot(command_prefix=commands.when_mentioned_or('/'), intents=intents)

    @bot.event
    async def on_ready():
        append_notification_log(f'discord: bot ready as {bot.user}')
        try:
            channel_id = str(_config_value('discord_status_channel_id') or '').strip()
            if channel_id:
                send_discord_status_channel_message('Discord bot connected and ready.')
        except Exception:
            pass

    await bot.start(token)


def main():
    asyncio.run(_run_bot())


if __name__ == '__main__':
    main()
