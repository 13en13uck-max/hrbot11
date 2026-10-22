import sys

from highrise.__main__ import run


def main():
    if len(sys.argv) != 4 or sys.argv[1] != "startbot":
        print("Usage: python main.py startbot <room_token> <api_key>")
        raise SystemExit(1)

    room_token = sys.argv[2]
    api_key = sys.argv[3]
    print(f"✅ Starting bot in room {room_token[:8]}...", flush=True)
    sys.argv = ["highrise", "bot:Bot", room_token, api_key]
    try:
        run()
        print("✅ Bot is online and in the room.", flush=True)
    except Exception as exc:
        print(f"❌ Failed to start: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
