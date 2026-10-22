import asyncio
import bot
from tests.test_bot import FakeUser, FakeHighrise

adapter = bot.Bot()
adapter.highrise = FakeHighrise()
adapter.app.highrise = adapter.highrise
adapter.tele_data = {"user_ranks": {"tester": "owner"}, "teleports": {}, "tele_ranks": {}}
adapter.highrise.get_room_users = lambda: type(
    "RoomUsers",
    (),
    {"content": [(type("RoomUser", (), {"id": FakeUser.id, "username": FakeUser.username})(), type("Pos", (), {"x": 1.0, "y": 2.0, "z": 3.0})())]},
)()

async def main():
    room_users = adapter.highrise.get_room_users()
    if hasattr(room_users, "content"):
        print("RAW_ROOM_USERS", room_users.content)
    pos = await adapter._get_user_position(FakeUser.id)
    print("POS", pos)
    print("POS_X", getattr(pos, 'x', None) if pos else None)
    try:
        response = await adapter.on_chat(FakeUser(), "!tele home vip")
        print("response:", response)
    except Exception as exc:
        print("EXCEPTION:", type(exc).__name__, exc)
        raise
    print("tele_data:", adapter.tele_data)
    print("user_ranks:", adapter.user_ranks)
    print("teleports:", adapter.teleports)
    print("tele_ranks:", adapter.tele_ranks)
    print("whispers:", adapter.highrise.whispers)

asyncio.run(main())
