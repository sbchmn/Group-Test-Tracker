"""Declarative metadata for notification channels and bot integrations.

This module holds only facts that several callers need to agree on -- which
channels exist, how to tell whether one is configured, and which plan entitlement
gates it. It deliberately knows nothing about *sending*, so the transports in
``notifications.py`` and the admin screens in ``routes.py`` can share one
definition without importing each other.

Adding a provider means adding one ``ChannelSpec`` here rather than editing the
channel chain, the settings badges and the integration badges separately.
"""

from dataclasses import dataclass

from .saas import entitlement_enabled


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    label: str
    required_keys: tuple = ()
    any_of_keys: tuple = ()
    entitlement: str = None
    supports_direct_message: bool = True


CHANNELS = (
    ChannelSpec(
        name="email",
        label="Email",
        required_keys=("mailjet_api_key", "mailjet_secret_key", "mailjet_sender_email"),
    ),
    ChannelSpec(
        name="telegram",
        label="Telegram",
        required_keys=("telegram_bot_token",),
    ),
    ChannelSpec(
        name="discord",
        label="Discord",
        any_of_keys=("discord_bot_token", "discord_webhook_url"),
        entitlement="discord_bot",
    ),
    ChannelSpec(
        name="root",
        label="Root",
        required_keys=("root_bridge_key_id", "root_bridge_secret", "root_status_channel_id"),
        # Root is not a separately-sold feature: it rides the Discord bot entitlement,
        # so a tenant on Core + Discord gets it by configuring bridge credentials and
        # needs no new control-plane entitlement key provisioned.
        entitlement="discord_bot",
        # Root has no bot-to-user DM: every message goes to a channel the whole
        # community can read, so it is a broadcast transport and never a member's
        # personal notification channel.
        supports_direct_message=False,
    ),
)

CHANNEL_NAMES = tuple(channel.name for channel in CHANNELS)

_BY_NAME = {channel.name: channel for channel in CHANNELS}


def _value_is_set(configs, key):
    return bool(str(configs.get(key) or "").strip())


def is_configured(name, configs):
    """Report whether a channel has everything it needs to attempt delivery."""
    channel = _BY_NAME.get(name)
    if channel is None:
        return False
    if not channel.required_keys and not channel.any_of_keys:
        return False
    if channel.required_keys and not all(_value_is_set(configs, key) for key in channel.required_keys):
        return False
    if channel.any_of_keys and not any(_value_is_set(configs, key) for key in channel.any_of_keys):
        return False
    return True


def configured_status(configs, names=None):
    """Build the {channel: configured} badge map used by the admin screens."""
    return {name: is_configured(name, configs) for name in (names or CHANNEL_NAMES)}


def entitlement_for(name):
    """Return the plan entitlement key that gates a channel, or None if ungated."""
    channel = _BY_NAME.get(name)
    return channel.entitlement if channel else None


def chat_channels():
    """Every channel except email, in the order they should be presented."""
    return tuple(name for name in CHANNEL_NAMES if name != "email")


def notification_channel_choices():
    """The ``User.notification_channel`` options, in presentation order.

    Derived from CHANNELS so a provider is selectable the moment it is declared here:
    the profile and admin forms used to hardcode the list, which meant a channel could
    be fully wired for delivery and still be unreachable from the UI. Broadcast-only
    transports are excluded -- a per-user channel must be able to reach the person.
    """
    return [
        (channel.name, channel.label)
        for channel in CHANNELS
        if channel.supports_direct_message
    ]


def available_notification_channel_choices(configs, current=None):
    """Only the channels this instance can actually deliver to right now.

    A chat provider is offered when the tenant is entitled to it *and* it is
    configured, so the UI cannot advertise a transport that would quietly fall back
    to email. Email is always available: it is the base product and the fallback, and
    hiding it could leave a form with no selectable option at all.

    ``current`` is the value already stored on the account and is always retained.
    SelectField validates against ``choices``, so dropping a saved channel that has
    since been unconfigured or de-entitled would make that profile unsavable rather
    than merely unselectable.
    """
    labels = {channel.name: channel.label for channel in CHANNELS}
    choices = []
    for channel in CHANNELS:
        if channel.name == "email":
            choices.append((channel.name, channel.label))
            continue
        if not channel.supports_direct_message:
            continue
        if channel.entitlement and not entitlement_enabled(channel.entitlement):
            continue
        if not is_configured(channel.name, configs):
            continue
        choices.append((channel.name, channel.label))

    if current and all(name != current for name, _ in choices):
        label = labels.get(current) or str(current)
        choices.append((current, f"{label} (not available)"))
    return choices
