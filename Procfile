web: gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 "app:create_app()"
discord-bot: python -m app.discord_bot
result-analysis-worker: flask --app app result-analysis-worker --poll-seconds 5
