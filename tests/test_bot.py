import tempfile
import unittest
import asyncio
import time
from datetime import timedelta
from unittest.mock import patch

import aiohttp
import bot
from bot import BlackjackGame, Database, WordChainGame


class DatabaseTests(unittest.TestCase):
    def test_default_database_path_is_next_to_bot_module(self):
        database = Database()
        try:
            self.assertEqual(
                database.conn.execute("PRAGMA database_list").fetchone()[2],
                bot.os.path.join(bot.os.path.dirname(bot.os.path.abspath(bot.__file__)), "bot.db"),
            )
        finally:
            database.conn.close()

    def test_user_can_be_created_and_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(f"{directory}/test.db")
            database.upsert_user("user-1", "Alex")
            database.increment("user-1", "messages")
            user = database.get_user("user-1")
            database.conn.close()

        self.assertEqual(user["username"], "Alex")
        self.assertEqual(user["messages"], 1)

    def test_internal_coins_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(f"{directory}/test.db")
            database.upsert_user("sender", "Sender")
            database.upsert_user("receiver", "Receiver")
            ok, error = database.transfer_coins("sender", "receiver", 25)
            sender_balance = database.get_balance("sender")
            receiver_balance = database.get_balance("receiver")
            database.conn.close()

        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(sender_balance, 75)
        self.assertEqual(receiver_balance, 125)

    def test_room_member_interaction_normalizes_identifier_types(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(f"{directory}/test.db")
            database.mark_room_interaction(12345)
            join_time = database.get_room_join_time("12345")
            database.conn.close()

        self.assertIsNotNone(join_time)


class GameTests(unittest.TestCase):
    def test_word_chain_accepts_matching_words(self):
        game = WordChainGame(None)
        self.assertIn("apple", game.start())
        self.assertIn("banana", game.submit("user-1", "banana"))

    def test_blackjack_starts_empty(self):
        game = BlackjackGame(None)
        self.assertIn("created", game.create().lower())
        self.assertIn("empty", game.lobby().lower())


class FakeHighrise:
    def __init__(self):
        self.emotes = []
        self.chats = []
        self.whispers = []
        self.my_id = "bot-user-id"
        self.move_calls = []
        self.tips = []

    async def chat(self, *args, **kwargs):
        self.chats.append((args, kwargs))

    async def send_message(self, *args, **kwargs):
        self.chats.append((args, kwargs))

    async def send_whisper(self, *args, **kwargs):
        self.whispers.append((args, kwargs))

    async def send_emote(self, *args, **kwargs):
        self.emotes.append((args, kwargs))

    async def get_room_users(self):
        target = type("RoomUser", (), {"id": "target-id", "username": "Target"})()
        target_two = type("RoomUser", (), {"id": "target-two", "username": "Second"})()
        configured_owner = type(
            "RoomUser", (), {"id": "configured-owner", "username": "configured-owner"}
        )()
        owner = type("RoomUser", (), {"id": "test-user", "username": "Tester"})()
        position = type("RoomPosition", (), {"x": 1.0, "y": 2.0, "z": 3.0})()
        return type(
            "RoomUsers",
            (),
            {
                "content": [
                    (target, None),
                    (target_two, None),
                    (configured_owner, None),
                    (owner, position),
                ]
            },
        )()

    async def teleport(self, user_id, position):
        self.teleport_call = (user_id, position)
        if not hasattr(self, "teleport_calls"):
            self.teleport_calls = []
        self.teleport_calls.append((user_id, position))

    async def move_user_to_room(self, user_id, room_id):
        self.move_calls.append((user_id, room_id))

    async def react(self, *_args, **_kwargs):
        return None

    async def tip_user(self, user_id, tip):
        self.tips.append((user_id, tip))
        return "success"

    async def get_inventory(self):
        return type("Inventory", (), {"items": []})()

    async def get_wallet(self):
        currency = type("Currency", (), {"type": "gold", "amount": 1234})()
        return type("Wallet", (), {"content": [currency]})()

    async def get_room_privilege(self, user_id):
        return "host" if user_id == "test-user" else "guest"


class FakeUser:
    id = "test-user"
    username = "Tester"


class TeleportSystemTests(unittest.TestCase):
    def setUp(self):
        bot.CONFIG["owner_id"] = ""
        self.adapter = bot.Bot()
        self.adapter.highrise = FakeHighrise()
        self.adapter.app.highrise = self.adapter.highrise

    def test_direct_named_teleport_checks_rank(self):
        async def exercise():
            self.adapter.tele_data = {
                "user_ranks": {"tester": "guest"},
                "teleports": {"vipspot": {"x": 10.0, "y": 20.0, "z": 30.0, "facing": 90.0}},
                "tele_ranks": {"vipspot": "vip"},
            }
            await self.adapter.on_chat(FakeUser(), "vipspot")
            self.assertEqual(len(self.adapter.highrise.whispers), 1)
            self.assertIn("requires rank vip", self.adapter.highrise.whispers[0][0][1].lower())

            self.adapter.tele_data["user_ranks"]["tester"] = "vip"
            self.adapter.highrise.whispers.clear()
            await self.adapter.on_chat(FakeUser(), "vipspot")
            self.assertEqual(self.adapter.highrise.teleport_call[0], FakeUser.id)

        asyncio.run(exercise())

    def test_setrank_and_tele_commands_save_data(self):
        async def exercise():
            self.adapter.tele_data = {
                "user_ranks": {"tester": "owner"},
                "teleports": {},
                "tele_ranks": {},
            }
            self.adapter.highrise.get_room_users = lambda: type(
                "RoomUsers",
                (),
                {"content": [(type("RoomUser", (), {"id": FakeUser.id, "username": FakeUser.username})(), type("Pos", (), {"x": 1.0, "y": 2.0, "z": 3.0})())]},
            )()
            await self.adapter.on_chat(FakeUser(), "!setrank Alice vip")
            self.assertEqual(self.adapter.tele_data["user_ranks"]["alice"], "vip")
            self.assertIn("rank for alice", self.adapter.highrise.whispers[-1][0][1].lower())

            await self.adapter.on_chat(FakeUser(), "!tele home vip")
            self.assertIn("home", self.adapter.tele_data["tele_ranks"])
            self.assertIn("home", self.adapter.tele_data["teleports"])
            self.assertIn("created", self.adapter.highrise.whispers[-1][0][1].lower())

            self.adapter.highrise.whispers.clear()
            await self.adapter.on_chat(FakeUser(), "!tele list")
            self.assertTrue(self.adapter.highrise.whispers)
            self.assertIn("home", self.adapter.highrise.whispers[-1][0][1].lower())

        asyncio.run(exercise())

    def test_tele_create_handles_missing_position_without_crashing(self):
        async def exercise():
            self.adapter.tele_data = {
                "user_ranks": {"tester": "coowner"},
                "teleports": {},
                "tele_ranks": {},
            }
            async def broken_get_room_users():
                raise RuntimeError("position lookup failed")
            self.adapter.highrise.get_room_users = broken_get_room_users

            await self.adapter.on_chat(FakeUser(), "!tele hidden vip")
            self.assertIn("could not get your position", self.adapter.highrise.whispers[-1][0][1].lower())
            self.assertNotIn("hidden", self.adapter.tele_data["teleports"])

        asyncio.run(exercise())

    def test_database_teleport_can_be_triggered_by_room_chat_name(self):
        async def exercise():
            self.adapter.db.set_tele_point("lounge", 10.0, 20.0, 30.0)

            await self.adapter.on_chat(FakeUser(), "lounge")

            self.assertEqual(self.adapter.highrise.teleport_call[0], FakeUser.id)
            position = self.adapter.highrise.teleport_call[1]
            self.assertEqual((position.x, position.y, position.z), (10.0, 20.0, 30.0))

        asyncio.run(exercise())


class FakeWebAPI:
    def __init__(self, room_id):
        self.room_id = room_id

    async def get_user(self, _user_id):
        room = type("ActiveRoom", (), {"id": self.room_id})()
        return type("UserData", (), {"active_room": room})()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        bot.CONFIG["owner_id"] = ""
        self.adapter = bot.Bot()
        self.adapter.highrise = FakeHighrise()
        self.adapter.app.highrise = self.adapter.highrise
        self.adapter.db.update_user(FakeUser.id, coins=100)

    def test_moderation_permissions_protect_owner_and_coowner(self):
        self.adapter.config["owner_id"] = "owner-id"
        self.adapter.db.upsert_user("coowner-id")
        self.adapter.db.set_role("coowner-id", "coowner")
        self.adapter.db.upsert_user("admin-id")
        self.adapter.db.set_role("admin-id", "admin")
        self.adapter.db.upsert_user("mod-id")
        self.adapter.db.set_role("mod-id", "mod")
        self.adapter.db.upsert_user("guest-id")

        self.assertTrue(self.adapter._can_moderate("owner-id"))
        self.assertTrue(self.adapter._can_moderate("coowner-id"))
        self.assertTrue(self.adapter._can_moderate("admin-id"))
        self.assertTrue(self.adapter._can_moderate("mod-id"))
        self.assertFalse(self.adapter._can_moderate("guest-id"))

        allowed, message = self.adapter._moderation_target_allowed(
            "admin-id", "owner-id", "Owner"
        )
        self.assertFalse(allowed)
        self.assertEqual(message, "❌ Can't moderate the Owner.")

        allowed, message = self.adapter._moderation_target_allowed(
            "admin-id", "coowner-id", "CoOwner"
        )
        self.assertFalse(allowed)
        self.assertIn("Co-Owner or Owner", message)

        allowed, message = self.adapter._moderation_target_allowed(
            "mod-id", "admin-id", "Admin"
        )
        self.assertFalse(allowed)
        self.assertIn("same rank or higher", message)

        allowed, message = self.adapter._moderation_target_allowed(
            "admin-id", "guest-id", "Guest"
        )
        self.assertTrue(allowed)
        self.assertIsNone(message)

    def test_bring_moves_bot_to_user_room_when_no_targets_are_given(self):
        async def exercise():
            self.adapter.webapi = FakeWebAPI("room-abc")
            self.adapter.highrise.my_id = "bot-user-id"
            response = await self.adapter._bring(FakeUser(), [])
            self.assertIn("joined", response.lower())
            self.assertEqual(self.adapter.highrise.move_calls[-1], ("bot-user-id", "room-abc"))

        asyncio.run(exercise())

    def test_every_command_alias_dispatches(self):
        async def exercise():
            async def fake_fetch(_url):
                return {
                    "meals": [{
                        "idMeal": "123",
                        "strMeal": "Test",
                        "strIngredient1": "Ingredient",
                        "strMeasure1": "1",
                        "strInstructions": "Cook.",
                    }]
                }

            self.adapter._fetch_url = fake_fetch
            for alias in bot.COMMAND_ALIASES:
                await self.adapter.on_chat(FakeUser(), f"!{alias}")

        asyncio.run(exercise())

    def test_refresh_command_reloads_state(self):
        async def exercise():
            self.adapter.config["owner_id"] = FakeUser.id
            self.adapter._restart_process = lambda: asyncio.sleep(0)
            response = await self.adapter.cmd_refresh(FakeUser(), [])
            self.assertIn("restarting", response.lower())
            await asyncio.sleep(0)

        asyncio.run(exercise())

    def test_refresh_requires_owner(self):
        async def exercise():
            self.adapter.config["owner_id"] = "owner-id"
            self.adapter.db.set_role(FakeUser.id, "guest")
            response = await self.adapter.cmd_refresh(FakeUser(), [])
            self.assertIn("Only the Owner or Co-Owner", response)

        asyncio.run(exercise())

    def test_coowner_can_refresh(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "coowner")
            self.adapter._restart_process = lambda: asyncio.sleep(0)
            response = await self.adapter.cmd_refresh(FakeUser(), [])
            self.assertIn("restarting", response.lower())
            await asyncio.sleep(0)

        asyncio.run(exercise())

    def test_status_reports_uptime_and_known_users(self):
        async def exercise():
            response = await self.adapter.dispatch(FakeUser(), "status", [])
            self.assertIn("Online", response)
            self.assertIn("Uptime:", response)
            self.assertRegex(response, r"Known users: \d+")

        asyncio.run(exercise())

    def test_startup_and_join_id_logging(self):
        async def exercise():
            async def fake_fetch(url):
                return {"compliment": "the room missed you."} if "complimentr" in url else {}

            self.adapter._fetch_url = fake_fetch
            room_info = type(
                "RoomInfo", (), {"owner_id": "room-owner-id", "room_name": "Test Room"}
            )()
            metadata = type("SessionMetadata", (), {"room_info": room_info})()
            await self.adapter.on_start(metadata)
            self.assertIsNotNone(self.adapter._queue_rules_task)
            await self.adapter.on_user_join(FakeUser(), None)
            self.assertIn("I'm back.", self.adapter.highrise.chats[-2][0][0])
            self.assertIn("@Tester is back.", self.adapter.highrise.chats[-1][0][0])

        asyncio.run(exercise())

    def test_queue_rules_repeat_every_ten_seconds(self):
        async def exercise():
            original_sleep = asyncio.sleep
            delays = []

            async def fake_sleep(delay):
                delays.append(delay)
                if len(delays) > 1:
                    await asyncio.Future()

            with patch.object(bot.asyncio, "sleep", fake_sleep):
                task = asyncio.create_task(self.adapter._queue_rules_loop())
                await original_sleep(0)
                self.assertEqual(
                    [args[0] for args, _kwargs in self.adapter.highrise.chats],
                    list(bot.QUEUE_RULES_MESSAGES),
                )
                self.assertTrue(
                    all(len(message) <= 500 for message in bot.QUEUE_RULES_MESSAGES)
                )
                self.assertEqual(delays, [10, 10])
                task.cancel()
                await original_sleep(0)

            self.assertTrue(task.done())

        asyncio.run(exercise())

    def test_welcome_messages_and_info_profile(self):
        async def exercise():
            async def fake_fetch(_url):
                return {"compliment": "you make the room better."}

            self.adapter._fetch_url = fake_fetch
            self.adapter.db.set_role(FakeUser.id, "guest")
            await self.adapter.on_user_join(FakeUser(), None)
            self.assertEqual(
                self.adapter.highrise.chats[-1][0][0],
                "👋 @Tester is back. you make the room better.",
            )
            response = await self.adapter._dispatch(FakeUser(), "info", [])
            self.assertIsNone(response)
            profile = self.adapter.highrise.whispers[-1][0][1]
            self.assertIn("PROFILE: 👤 Tester", profile)
            self.assertIn("Time in room:", profile)
            for field in (
                "Messages sent:", "Tips given:", "Tips received:",
                "Games played:", "Achievements:", "Daily streak:",
                "Bio:", "Status:", "Birthday:",
            ):
                self.assertNotIn(field, profile)

        asyncio.run(exercise())

    def test_leave_message_uses_random_shared_responses(self):
        async def exercise():
            async def fake_fetch(_url):
                return {"insult": "the room is already quieter."}

            self.adapter._fetch_url = fake_fetch
            await self.adapter.on_user_leave(FakeUser())
            message = self.adapter.highrise.chats[-1][0][0]
            self.assertEqual(message, "💨 @Tester left. the room is already quieter.")

        asyncio.run(exercise())

    def test_bot_leave_message_uses_advice_api(self):
        async def exercise():
            self.adapter.highrise.my_id = FakeUser.id

            async def fake_fetch(url):
                self.assertEqual(url, "https://api.adviceslip.com/advice")
                return {"slip": {"advice": "Take a break and come back stronger."}}

            self.adapter._fetch_url = fake_fetch
            await self.adapter.on_user_leave(FakeUser())
            self.assertEqual(
                self.adapter.highrise.chats[-1][0][0],
                "👋 I'm out. Take a break and come back stronger.",
            )

        asyncio.run(exercise())

    def test_roast_once_ignores_bot_and_posts_insult(self):
        async def exercise():
            async def fake_fetch(_url):
                return {"insult": "You are powered by low batteries."}

            self.adapter._fetch_url = fake_fetch
            await self.adapter._roast_once()
            roast = self.adapter.highrise.chats[-1][0][0]
            self.assertTrue(roast.startswith("🔥 @"))
            self.assertIn("You are powered by low batteries.", roast)
            self.assertNotIn("bot-user-id", roast)

        asyncio.run(exercise())

    def test_roast_uses_cache_busting_and_rejects_duplicate(self):
        async def exercise():
            responses = [
                {"insult": "You are powered by low batteries."},
                {"insult": "You are powered by low batteries."},
                {"insult": "Your jokes need a software update."},
            ]
            urls = []

            async def fake_fetch(url):
                urls.append(url)
                return responses.pop(0)

            self.adapter.last_roast = "You are powered by low batteries."
            self.adapter._fetch_url = fake_fetch
            await self.adapter._roast_once()

            roast = self.adapter.highrise.chats[-1][0][0]
            self.assertIn("software update", roast)
            self.assertEqual(len(urls), 3)
            self.assertTrue(
                all(
                    url.startswith(
                        "https://evilinsult.com/generate_insult.php"
                        "?lang=en&type=json&random="
                    )
                    for url in urls
                )
            )
            self.assertEqual(self.adapter.last_roast, "Your jokes need a software update.")

        asyncio.run(exercise())

    def test_roast_skips_cycle_after_three_failed_attempts(self):
        async def exercise():
            attempts = 0

            async def fake_fetch(_url):
                nonlocal attempts
                attempts += 1
                raise RuntimeError("API unavailable")

            self.adapter._fetch_url = fake_fetch
            chats_before = len(self.adapter.highrise.chats)
            await self.adapter._roast_once()
            self.assertEqual(attempts, 5)
            self.assertEqual(len(self.adapter.highrise.chats), chats_before)

        asyncio.run(exercise())

    def test_roast_task_can_be_cancelled(self):
        async def exercise():
            task = asyncio.create_task(self.adapter._roast_loop())
            self.adapter._roast_task = task
            self.adapter._cancel_roast_task()
            await asyncio.sleep(0)
            self.assertTrue(task.cancelled())
            self.assertIsNone(self.adapter._roast_task)

        asyncio.run(exercise())

    def test_roast_skips_banned_insult_and_retries(self):
        async def exercise():
            responses = [
                {"insult": "Your mother is calling."},
                {"insult": "You are powered by low batteries."},
            ]

            async def fake_fetch(_url):
                return responses.pop(0)

            self.adapter._fetch_url = fake_fetch
            await self.adapter._roast_once()
            roast = self.adapter.highrise.chats[-1][0][0]
            self.assertIn("low batteries", roast)
            self.assertNotIn("mother", roast.casefold())

        asyncio.run(exercise())

    def test_roast_skips_cycle_after_three_banned_insults(self):
        async def exercise():
            async def fake_fetch(_url):
                return {"insult": "Your family is calling."}

            self.adapter._fetch_url = fake_fetch
            chats_before = len(self.adapter.highrise.chats)
            await self.adapter._roast_once()
            self.assertEqual(len(self.adapter.highrise.chats), chats_before)

        asyncio.run(exercise())

    def test_info_reports_live_room_members_duration(self):
        async def exercise():
            self.adapter.db.conn.execute(
                "INSERT OR REPLACE INTO room_members (user_id, join_time) VALUES (?, ?)",
                (FakeUser.id, time.time() - timedelta(days=5, hours=9, minutes=22).total_seconds()),
            )
            self.adapter.db.conn.commit()
            await self.adapter._dispatch(FakeUser(), "info", [])
            profile = self.adapter.highrise.whispers[-1][0][1]
            self.assertRegex(profile, r"Time in room: 5d 9h 2[1-2]m")
            self.adapter.db.conn.execute(
                "DELETE FROM room_members WHERE user_id=?", (FakeUser.id,)
            )
            self.adapter.db.conn.commit()
            await self.adapter._dispatch(FakeUser(), "info", [])
            self.assertNotIn("Time in room: Not in room", self.adapter.highrise.whispers[-1][0][1])

        asyncio.run(exercise())

    def test_nickname_is_used_in_welcome_message(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "admin")
            response = await self.adapter._dispatch(
                FakeUser(), "nickname", ["@Target", "dickhead"]
            )
            self.assertIn("nickname is now dickhead", response)
            target = type("TargetUser", (), {"id": "target-id", "username": "Target"})()
            await self.adapter.on_user_join(target, None)
            self.assertIn("dickhead", self.adapter.highrise.chats[-1][0][0])
            self.assertNotIn("Target!", self.adapter.highrise.chats[-1][0][0])
            await self.adapter.on_user_leave(target)
            self.assertIn("dickhead", self.adapter.highrise.chats[-1][0][0])
            self.assertNotIn("Target!", self.adapter.highrise.chats[-1][0][0])

        asyncio.run(exercise())

    def test_tipall_tips_every_current_room_user(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "admin")
            response = await self.adapter._dispatch(FakeUser(), "tipall", ["5"])
            self.assertIn("Tipped 4 users 5 gold each", response)
            self.assertEqual(len(self.adapter.highrise.tips), 4 * 1)
            self.assertTrue(all(tip == ("gold_bar_5") for _, tip in self.adapter.highrise.tips))
            announcements = [args[0] for args, _kwargs in self.adapter.highrise.chats]
            self.assertIn("🪙 @Target was tipped 5 gold.", announcements)

        asyncio.run(exercise())

    def test_recipe_command_formats_random_recipe(self):
        async def exercise():
            responses = [
                {"meals": [{"idMeal": "123"}]},
                {
                    "meals": [{
                        "strMeal": "Test Pasta",
                        "strCategory": "Pasta",
                        "strArea": "Italian",
                        "strMealThumb": "https://example.test/pasta.jpg",
                        "strSource": "https://example.test/source",
                        "strIngredient1": "Tomato",
                        "strMeasure1": "2 cups",
                        "strIngredient2": "",
                        "strMeasure2": "",
                        "strInstructions": "Cook the pasta.",
                    }]
                },
            ]

            async def fake_fetch(_url):
                return responses.pop(0)

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "recipe", ["italian"])
            self.assertIsNone(response)
            recipe = self.adapter.highrise.chats[-1][0][0]
            self.assertIn("RECIPE: Test Pasta", recipe)
            self.assertIn("• Tomato (2 cups)", recipe)
            self.assertIn("Cook the pasta.", recipe)

        asyncio.run(exercise())

    def test_randomfact_command_formats_fact_and_supports_alias(self):
        async def exercise():
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                return {"text": "Bananas are berries."}

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(
                FakeUser(), "randomfact", ["animals"]
            )
            self.assertIsNone(response)
            self.assertIn("category=animals", requested_urls[0])
            fact = self.adapter.highrise.chats[-1][0][0]
            self.assertIn("🧠 RANDOM FACT", fact)
            self.assertIn("Bananas are berries.", fact)

        asyncio.run(exercise())

    def test_facts_command_fetches_and_formats_api_fact(self):
        async def exercise():
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                return {"text": "Octopuses have three hearts."}

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "facts", [])
            self.assertIsNone(response)
            self.assertEqual(
                requested_urls,
                ["https://uselessfacts.jsph.pl/api/v2/facts/random"],
            )
            self.assertEqual(
                self.adapter.highrise.chats[-1][0][0],
                "💡 Octopuses have three hearts.",
            )

        asyncio.run(exercise())

    def test_facts_command_reports_api_failures(self):
        async def exercise():
            async def failed_fetch(_url):
                raise TimeoutError("request timed out")

            self.adapter._fetch_url = failed_fetch
            await self.adapter._dispatch(FakeUser(), "facts", [])
            self.assertEqual(
                self.adapter.highrise.chats[-1][0][0],
                "❌ Couldn't fetch a fact right now. Try again later.",
            )

        asyncio.run(exercise())

    def test_dare_and_truth_use_tagged_api_responses(self):
        async def exercise():
            class FakeResponse:
                status = 200

                async def json(self):
                    return {"question": "I like pizza."}

            class FakeRequest:
                async def __aenter__(self):
                    return FakeResponse()

                async def __aexit__(self, *_args):
                    return None

            class FakeSession:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                def get(self, _url, timeout):
                    self.assert_timeout(timeout)
                    return FakeRequest()

                @staticmethod
                def assert_timeout(timeout):
                    self.assertEqual(timeout.total, 3)

            with patch.object(bot.aiohttp, "ClientSession", return_value=FakeSession()):
                await self.adapter.cmd_dare(FakeUser(), ["@Target"])
                await self.adapter.cmd_truth(FakeUser(), ["@Target"])
                self.assertEqual(
                    self.adapter.highrise.chats[-2][0][0],
                    "⚡ DARE for Target: I like pizza.",
                )
                self.assertEqual(
                    self.adapter.highrise.chats[-1][0][0],
                    "🎯 TRUTH for Target: I like pizza.",
                )

        asyncio.run(exercise())

    def test_truth_command_is_scheduled_without_waiting_in_on_chat(self):
        async def exercise():
            started = asyncio.Event()
            release = asyncio.Event()

            async def fake_fetch(_user, _args):
                started.set()
                await release.wait()

            self.adapter.fetch_truth = fake_fetch
            await self.adapter.on_chat(FakeUser(), "!truth")
            self.assertTrue(self.adapter._tasks)
            await started.wait()
            release.set()
            await asyncio.gather(*list(self.adapter._tasks))

        asyncio.run(exercise())

    def test_dare_and_truth_fall_back_when_api_fails(self):
        async def exercise():
            class FakeSession:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                def get(self, _url, timeout):
                    raise TimeoutError("timed out")

            with patch.object(bot.aiohttp, "ClientSession", return_value=FakeSession()):
                await self.adapter.cmd_dare(FakeUser(), [])
                await self.adapter.cmd_truth(FakeUser(), [])
                self.assertEqual(
                    self.adapter.highrise.chats[-2][0][0],
                    "Could not fetch. Try again.",
                )
                self.assertEqual(
                    self.adapter.highrise.chats[-1][0][0],
                    "Could not fetch. Try again.",
                )

        asyncio.run(exercise())

    def test_dare_and_truth_report_non_200_responses(self):
        async def exercise():
            class FakeResponse:
                status = 500

                async def json(self):
                    return {"question": "should not be used"}

            class FakeRequest:
                async def __aenter__(self):
                    return FakeResponse()

                async def __aexit__(self, *_args):
                    return None

            class FakeSession:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                def get(self, _url, timeout):
                    return FakeRequest()

            with patch.object(bot.aiohttp, "ClientSession", return_value=FakeSession()):
                await self.adapter.cmd_dare(FakeUser(), [])
                await self.adapter.cmd_truth(FakeUser(), [])
                self.assertEqual(
                    self.adapter.highrise.chats[-2][0][0],
                    "Could not fetch. Try again.",
                )
                self.assertEqual(
                    self.adapter.highrise.chats[-1][0][0],
                    "Could not fetch. Try again.",
                )

        asyncio.run(exercise())

    def test_dare_and_truth_require_a_tagged_user(self):
        async def exercise():
            self.adapter.highrise.whispers.clear()
            await self.adapter.cmd_dare(FakeUser(), ["Target"])
            await self.adapter.cmd_truth(FakeUser(), ["Target"])
            self.assertEqual(
                self.adapter.highrise.whispers[-2][0][1],
                "Usage: `!dare` or `!dare @user`",
            )
            self.assertEqual(
                self.adapter.highrise.whispers[-1][0][1],
                "Usage: `!truth` or `!truth @user`",
            )

        asyncio.run(exercise())

    def test_rate_and_who_format_api_responses(self):
        async def exercise():
            requested_urls = []
            evil_calls = 0

            async def fake_fetch(url):
                nonlocal evil_calls
                requested_urls.append(url)
                if url.startswith("https://evilinsult.com/"):
                    evil_calls += 1
                    insult = "you are a mess." if evil_calls == 1 else "you are chaotic."
                    return {"insult": insult}
                return {"compliment": "you are brilliant."}

            self.adapter._fetch_url = fake_fetch
            with patch("bot.random.choice", side_effect=["good", "bad", "good", "bad"]):
                good_rate = await self.adapter._dispatch(FakeUser(), "rate", ["@Target"])
                bad_rate = await self.adapter._dispatch(FakeUser(), "rate", ["@Target"])
                good_who = await self.adapter._dispatch(FakeUser(), "who", ["@Target"])
                bad_who = await self.adapter._dispatch(FakeUser(), "who", ["@Target"])

            self.assertRegex(good_rate, r"^⭐ @Target: ([1-9]|10)/10 — you are brilliant\.$")
            self.assertRegex(bad_rate, r"^⭐ @Target: ([1-9]|10)/10 — you are a mess\.$")
            self.assertEqual(good_who, "🔍 Who is @Target? You are brilliant.")
            self.assertEqual(bad_who, "🔍 Who is @Target? you are chaotic.")
            self.assertTrue(
                requested_urls[0] == "https://complimentr.com/api"
            )
            self.assertRegex(requested_urls[1], r"^https://evilinsult\.com/generate_insult\.php\?lang=en&type=json&random=\d+$")
            self.assertEqual(requested_urls[2], "https://complimentr.com/api")
            self.assertRegex(requested_urls[3], r"^https://evilinsult\.com/generate_insult\.php\?lang=en&type=json&random=\d+$")

        asyncio.run(exercise())

    def test_rate_and_who_fall_back_when_api_fails(self):
        async def exercise():
            async def failed_fetch(_url):
                raise TimeoutError("timed out")

            self.adapter._fetch_url = failed_fetch
            rate = await self.adapter._dispatch(FakeUser(), "rate", ["@Target"])
            who = await self.adapter._dispatch(FakeUser(), "who", ["@Target"])

            self.assertTrue(any(rate.endswith(item) for item in bot.RATE_FALLBACK))
            self.assertTrue(any(who.endswith(item) for item in bot.WHO_FALLBACK))

        asyncio.run(exercise())

    def test_rate_and_who_require_a_tagged_user(self):
        async def exercise():
            self.assertEqual(
                await self.adapter._dispatch(FakeUser(), "rate", []),
                "Usage: `!rate @user`",
            )
            self.assertEqual(
                await self.adapter._dispatch(FakeUser(), "who", []),
                "Usage: `!who @user`",
            )

        asyncio.run(exercise())

    def test_api_values_are_html_unescaped(self):
        self.assertEqual(
            bot._decode_api_value({"text": "That&#039;s &amp; brilliant."}),
            {"text": "That's & brilliant."},
        )

    def test_riddle_uses_api_and_falls_back_to_alternate_source(self):
        async def exercise():
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                if len(requested_urls) == 1:
                    raise TimeoutError("primary unavailable")
                return {"riddle": "What&#039;s up?", "answer": "The sky."}

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "riddle", [])

            self.assertEqual(
                response,
                "🧩 What's up?\nYou have 6 guesses. Type your answer in chat!",
            )
            self.assertEqual(
                bot.active_games["riddle"]["answer"],
                "The sky.",
            )
            self.assertEqual(
                requested_urls,
                [
                    "https://riddles.io/api/riddles/random",
                    "https://riddles-api.vercel.app/random",
                ],
            )

        asyncio.run(exercise())

    def test_riddle_guess_flow_hides_answer_and_allows_six_attempts(self):
        async def exercise():
            async def fake_fetch(_url):
                return {"riddle": "What is above you?", "answer": "The sky"}

            self.adapter._fetch_url = fake_fetch
            opening = await self.adapter._dispatch(FakeUser(), "riddle", [])
            self.assertNotIn("The sky", opening)
            self.assertEqual(
                await self.adapter._handle_game_message(FakeUser(), "hi"), ""
            )
            wrong = await self.adapter._handle_game_message(FakeUser(), "cloud")
            self.assertIn("5 guesses left", wrong)
            solved = await self.adapter._handle_game_message(FakeUser(), " THE SKY ")
            self.assertEqual(
                solved,
                '🧠 @Tester solved it! The answer was "The sky".',
            )
            self.assertNotIn("riddle", bot.active_games)

        asyncio.run(exercise())

    def test_joke_formats_decoded_api_response(self):
        async def exercise():
            async def fake_fetch(url):
                self.assertEqual(
                    url,
                    "https://official-joke-api.appspot.com/random_joke",
                )
                return {
                    "setup": "Why did it say &#039;hello&#039;?",
                    "punchline": "Because it was &amp; friendly.",
                }

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "joke", [])
            self.assertEqual(
                response,
                "😂 Why did it say 'hello'?\nBecause it was & friendly.",
            )

        asyncio.run(exercise())

    def test_djoke_formats_single_and_two_part_api_responses(self):
        async def exercise():
            responses = [
                {"type": "single", "joke": "A dark &amp; funny joke."},
                {"type": "twopart", "setup": "Why?", "delivery": "Because &#039;reasons.&#039;"},
            ]

            async def fake_fetch(url):
                self.assertEqual(url, "https://v2.jokeapi.dev/joke/Dark")
                return responses.pop(0)

            self.adapter._fetch_url = fake_fetch
            first = await self.adapter._dispatch(FakeUser(), "djoke", [])
            second = await self.adapter._dispatch(FakeUser(), "djoke", [])

            self.assertEqual(first, "🖤 A dark & funny joke.")
            self.assertEqual(second, "🖤 Why?\nBecause 'reasons.'")

        asyncio.run(exercise())

    def test_djoke_uses_backup_api_after_primary_attempts_fail(self):
        async def exercise():
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                if "jokeapi" in url:
                    raise TimeoutError("primary unavailable")
                return {"buildup": "Backup setup", "punchline": "Backup punchline"}

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "djoke", [])

            self.assertEqual(
                requested_urls,
                ["https://v2.jokeapi.dev/joke/Dark"] * 5
                + ["https://peter-api.up.railway.app/api/darkjoke"],
            )
            self.assertEqual(response, "🖤 Backup setup\nBackup punchline")

        asyncio.run(exercise())

    def test_booktok_formats_recite_quote_and_unescapes_html(self):
        async def exercise():
            async def fake_fetch(url):
                self.assertEqual(
                    url,
                    "https://recite.onrender.com/random/quote-from-db",
                )
                return [{
                    "quote": "A &amp; memorable quote.",
                    "author": "A &amp; Author",
                    "book": "The &#039;Book&#039;",
                }]

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "booktok", [])

            self.assertEqual(
                response,
                '📖 "A & memorable quote."\n— A & Author, *The \'Book\'*',
            )

        asyncio.run(exercise())

    def test_booktok_retries_duplicates_five_times_then_returns_error(self):
        async def exercise():
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                return [{
                    "quote": "Already sent",
                    "author": "Author",
                    "book": "Book",
                }]

            duplicate = '📖 "Already sent"\n— Author, *Book*'
            bot.sent_items.add(duplicate)
            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "booktok", [])

            self.assertEqual(response, "❌ Couldn't fetch a quote. Try again.")
            self.assertEqual(len(requested_urls), 5)

        asyncio.run(exercise())

    def test_memes_formats_decoded_meme_and_avoids_duplicate_urls(self):
        async def exercise():
            responses = [
                {"url": "https://example.test/meme.jpg", "title": "A &amp; B", "subreddit": "funny"},
            ]

            async def fake_fetch(_url):
                return responses.pop(0)

            self.adapter._fetch_url = fake_fetch
            await self.adapter._dispatch(FakeUser(), "memes", [])
            self.assertEqual(
                self.adapter.highrise.chats[-1][0][0],
                "🖼️ r/funny: A & B\nhttps://example.test/meme.jpg",
            )

        asyncio.run(exercise())

    def test_watch_pending_flow_and_history_summary(self):
        async def exercise():
            watch_prompt = await self.adapter._dispatch(FakeUser(), "watch", [])
            self.assertIn("Action | Drama | Comedy", watch_prompt)
            self.assertTrue(bot.pending_watch[FakeUser.id])

            async def fake_fetch(url):
                if "themoviedb" in url:
                    return {"results": [{
                        "media_type": "movie",
                        "title": "Test Film",
                        "release_date": "2024-01-01",
                        "vote_average": 8.5,
                        "overview": "A " + ("long " * 80),
                    }]}
                return {
                    "title": "Alan Turing",
                    "description": "Computer scientist",
                    "extract": "Alan Turing&#039;s work changed computing.",
                }

            self.adapter._fetch_url = fake_fetch
            await self.adapter._handle_pending_watch(FakeUser(), "cOmEdY")
            suggestion = self.adapter.highrise.chats[-1][0][0]
            self.assertIn("**Test Film** (2024)", suggestion)
            self.assertTrue(suggestion.endswith("..."))
            self.assertNotIn(FakeUser.id, bot.pending_watch)

            async def fake_history(_subject):
                return "📜 **Alan Turing**\nComputer scientist\n\nAlan Turing's work changed computing."

            self.adapter.fetch_history = fake_history
            history = await self.adapter._dispatch(FakeUser(), "history", ["turing", "machine"])
            self.assertEqual(
                history,
                "📜 **Alan Turing**\nComputer scientist\n\nAlan Turing's work changed computing.",
            )

        asyncio.run(exercise())

    def test_history_searches_for_exact_title_before_fetching_summary(self):
        async def exercise():
            requested_urls = []

            class FakeResponse:
                def __init__(self, status, data=None):
                    self.status = status
                    self.data = data

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def json(self):
                    return self.data

            class FakeSession:
                def __init__(self, response):
                    self.response = response

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                def get(self, url, timeout):
                    requested_urls.append(url)
                    return self.response

            sessions = [
                FakeSession(FakeResponse(200, [
                    "roman empire",
                    ["Roman Empire"],
                    ["A historical empire."],
                    ["https://en.wikipedia.org/wiki/Roman_Empire"],
                ])),
                FakeSession(FakeResponse(200, {
                    "title": "Roman Empire",
                    "description": "Ancient empire",
                    "extract": "A historical empire.",
                })),
            ]

            with patch.object(aiohttp, "ClientSession", side_effect=sessions):
                history = await self.adapter._dispatch(FakeUser(), "history", ["roman", "empire"])

            self.assertEqual(
                requested_urls,
                [
                    "https://en.wikipedia.org/w/api.php?action=opensearch&search=roman%20empire&limit=1&namespace=0&format=json",
                    "https://en.wikipedia.org/api/rest_v1/page/summary/Roman_Empire",
                ],
            )
            self.assertIn("**Roman Empire**", history)

        asyncio.run(exercise())

    def test_watch_supports_tv_names_and_branded_query_fallback(self):
        async def exercise():
            requested_urls = []
            responses = [
                {"results": [{
                    "media_type": "tv",
                    "name": "Marvel Test Series",
                    "first_air_date": "2023-01-01",
                    "vote_average": 7.5,
                    "overview": "A superhero series.",
                }]},
                {"results": [
                    {"media_type": "movie", "title": "Marvel Film One", "release_date": "2022-01-01", "vote_average": 8, "overview": "One."},
                    {"media_type": "movie", "title": "Marvel Film Two", "release_date": "2021-01-01", "vote_average": 7, "overview": "Two."},
                    {"media_type": "tv", "name": "Marvel Show Three", "first_air_date": "2020-01-01", "vote_average": 9, "overview": "Three."},
                ]},
            ]

            async def fake_fetch(url):
                requested_urls.append(url)
                return responses.pop(0)

            self.adapter._fetch_url = fake_fetch
            await self.adapter.cmd_watch(FakeUser(), [])
            await self.adapter._handle_pending_watch(FakeUser(), "MARVEL")
            suggestion = self.adapter.highrise.chats[-1][0][0]
            self.assertIn("Marvel", suggestion)
            self.assertEqual(len(requested_urls), 2)
            self.assertIn("query=marvel&", requested_urls[0])
            self.assertIn("query=marvel%20movies&", requested_urls[1])

        asyncio.run(exercise())

    def test_watch_genres_use_tmdb_discover_with_genre_id(self):
        async def exercise():
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                return {"results": [{
                    "title": "The Conjuring",
                    "release_date": "2013-01-01",
                    "vote_average": 7.5,
                    "overview": "A horror film.",
                }]}

            self.adapter._fetch_url = fake_fetch
            await self.adapter._handle_pending_watch(FakeUser(), "horror")

            self.assertEqual(
                requested_urls,
                [
                    "https://api.themoviedb.org/3/discover/movie?"
                    "api_key=510da5917461c6982db4ecb94696e030"
                    "&with_genres=27&sort_by=popularity.desc&language=en-US"
                ],
            )
            self.assertIn("**The Conjuring** (2013)", self.adapter.highrise.chats[-1][0][0])

        asyncio.run(exercise())

    def test_hangman_fetches_word_and_dictionary_hint(self):
        async def exercise():
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                if "random-word-api" in url:
                    return ["planet"]
                return [{"meanings": [{"definitions": [{
                    "definition": "A celestial body orbiting a star."
                }]}]}]

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "hangman", [])
            self.assertIn("📖 Hint: A celestial body orbiting a star.", response)
            self.assertIn("The word has 6 letters", response)
            self.assertIn("_ _ _ _ _ _", response)
            self.assertRegex(
                requested_urls[0],
                r"https://random-word-api\.vercel\.app/api/word\?length=[5-9]$",
            )
            self.assertIn("dictionaryapi.dev/api/v2/entries/en/planet", requested_urls[1])

        asyncio.run(exercise())

    def test_hangman_uses_mystery_hint_and_marks_word_after_solve(self):
        async def exercise():
            async def fake_fetch(url):
                if "random-word-api" in url:
                    return ["apple"]
                raise RuntimeError("dictionary unavailable")

            self.adapter._fetch_url = fake_fetch
            response = await self.adapter._dispatch(FakeUser(), "hangman", [])
            self.assertIn("📖 Hint: mystery", response)
            self.assertNotIn("apple", bot.sent_items)

            for letter in "aple":
                result = await self.adapter._handle_game_message(FakeUser(), letter)
            self.assertIn("solved it", result)
            self.assertNotIn("hangman", bot.active_games)
            self.assertIn("apple", bot.sent_items)

        asyncio.run(exercise())

    def test_hangman_has_specific_active_message(self):
        async def exercise():
            bot.active_games["hangman"] = {
                "word": "planet", "hint": "mystery", "guessed": set(), "wrong": 0
            }
            response = await self.adapter._dispatch(FakeUser(), "hangman", [])
            self.assertEqual(response, "⏳ Hangman is already in progress!")

        asyncio.run(exercise())

    def test_hangman_allows_eight_wrong_guesses(self):
        async def exercise():
            bot.active_games["hangman"] = {
                "word": "planet", "hint": "mystery", "guessed": set(), "wrong": 7
            }
            result = await self.adapter._handle_game_message(FakeUser(), "z")
            self.assertIn("❌ Wrong! (8/8)", result)
            self.assertIn("  |  💀", result)
            self.assertIn("💀 8 wrong guesses. The word was planet.", result)
            self.assertNotIn("hangman", bot.active_games)

        asyncio.run(exercise())

    def test_api_content_retries_duplicates_before_returning(self):
        async def exercise():
            responses = [
                {"compliment": "You are brilliant."},
                {"compliment": "You are thoughtful."},
            ]
            requested_urls = []

            async def fake_fetch(url):
                requested_urls.append(url)
                return responses.pop(0)

            bot.sent_items.add("You are brilliant.")
            self.adapter._fetch_url = fake_fetch
            with patch("bot.random.choice", return_value="good"):
                response = await self.adapter._dispatch(FakeUser(), "rate", ["@Target"])

            self.assertIn("You are thoughtful.", response)
            self.assertEqual(len(requested_urls), 2)
            self.assertIn("You are thoughtful.", bot.sent_items)

        asyncio.run(exercise())

    def test_stop_cancels_current_emote_for_user(self):
        async def exercise():
            await self.adapter.on_chat(FakeUser(), "!ghostfloat @Target")
            self.assertEqual(self.adapter.active_emotes["target-id"], "ghostfloat")
            target = type("TargetUser", (), {"id": "target-id", "username": "Target"})()
            await self.adapter.on_chat(target, "!stop")
            self.assertNotIn("target-id", self.adapter.active_emotes)
            self.assertIn(
                "⏹️ Stopped ghostfloat on @Target.",
                self.adapter.highrise.chats[-1][0][0],
            )

            response = await self.adapter._dispatch(target, "stop", [])
            self.assertEqual(response, "⏹️ No emote is playing.")

        asyncio.run(exercise())

    def test_summon_teleports_target_for_admin(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "admin")
            self.adapter._resolve_target = lambda _mention: asyncio.sleep(0, result="target-id")
            self.adapter._get_user_position = lambda _user_id: asyncio.sleep(
                0, result=type("Position", (), {"x": 4.0, "y": 5.0, "z": 6.0})()
            )
            response = await self.adapter._dispatch(FakeUser(), "summon", ["@Target"])
            self.assertEqual(response, "⚡ **@Target** was summoned to my location.")
            self.assertEqual(
                self.adapter.highrise.teleport_calls[-1][0], "target-id"
            )
            position = self.adapter.highrise.teleport_calls[-1][1]
            self.assertEqual((position.x, position.y, position.z), (4.0, 5.0, 6.0))

        asyncio.run(exercise())

    def test_summon_requires_admin_or_owner(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "guest")
            response = await self.adapter._dispatch(FakeUser(), "summon", ["@Target"])
            self.assertEqual(response, "❌ You don't have permission to use this command.")

        asyncio.run(exercise())

    def test_coowner_can_use_summon(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "coowner")
            self.adapter._resolve_target = lambda mention: asyncio.sleep(0, result="target-id")
            self.adapter._get_user_position = lambda user_id: asyncio.sleep(
                0, result=type("Position", (), {"x": 1.0, "y": 2.0, "z": 3.0})()
            )
            response = await self.adapter._dispatch(FakeUser(), "summon", ["@Target"])
            self.assertEqual(response, "⚡ **@Target** was summoned to my location.")

        asyncio.run(exercise())

    def test_admin_log_shows_last_entries_for_coowner(self):
        async def exercise():
            bot.admin_log.clear()
            bot.admin_log.extend(
                f"[12:00:{index:02d}] Tester action Target"
                for index in range(35)
            )
            self.adapter.db.set_role(FakeUser.id, "coowner")
            response = await self.adapter._dispatch(FakeUser(), "log", [])
            self.assertTrue(response.startswith("```\n"))
            self.assertTrue(response.endswith("\n```"))
            self.assertNotIn("[12:00:00]", response)
            self.assertIn("[12:00:34] Tester action Target", response)

        asyncio.run(exercise())

    def test_admin_log_denies_guest(self):
        async def exercise():
            bot.admin_log.clear()
            self.adapter.db.set_role(FakeUser.id, "guest")
            response = await self.adapter._dispatch(FakeUser(), "log", [])
            self.assertEqual(response, "❌ You don't have permission to use this command.")

        asyncio.run(exercise())

    def test_wallet_reports_bot_gold_privately(self):
        async def exercise():
            response = await self.adapter._dispatch(FakeUser(), "wallet", [])
            self.assertIsNone(response)
            self.assertEqual(
                self.adapter.highrise.whispers[-1][0],
                (FakeUser.id, "💰 Bot wallet: 1,234g"),
            )

        asyncio.run(exercise())

    def test_flip_requires_choice_and_resets_after_result(self):
        async def exercise():
            async def fast_sleep(_seconds):
                return None

            original_sleep = bot.asyncio.sleep
            bot.asyncio.sleep = fast_sleep
            try:
                await self.adapter._dispatch(FakeUser(), "flip", [])
                self.assertTrue(self.adapter.flip_active)
                await self.adapter._dispatch(FakeUser(), "heads", [])
                self.assertFalse(self.adapter.flip_active)
                self.assertIsNone(self.adapter.flip_player)
                self.assertIsNone(self.adapter.flip_choice)
                self.assertTrue(any("It landed on" in args[0] for args, _ in self.adapter.highrise.chats))
            finally:
                bot.asyncio.sleep = original_sleep

        asyncio.run(exercise())

    def test_kms_flow_fetches_three_names_and_resets(self):
        async def exercise():
            self.adapter.config["tmdb_key"] = "test-key"

            async def fake_names():
                return ["Actor One", "Actor Two", "Actor Three"]

            async def fast_sleep(_seconds):
                return None

            self.adapter._fetch_kms_names = fake_names
            original_sleep = bot.asyncio.sleep
            bot.asyncio.sleep = fast_sleep
            try:
                await self.adapter._dispatch(FakeUser(), "kms", [])
                self.assertTrue(self.adapter.kms_active)
                await self.adapter._dispatch(FakeUser(), "kiss", ["1"])
                await self.adapter._dispatch(FakeUser(), "marry", ["1"])
                await self.adapter._dispatch(FakeUser(), "kill", [])
                self.assertFalse(self.adapter.kms_active)
                self.assertIn(
                    "KISS MARRY KILL",
                    self.adapter.highrise.chats[-1][0][0],
                )
            finally:
                bot.asyncio.sleep = original_sleep
                self.adapter.config["tmdb_key"] = ""

        asyncio.run(exercise())

    def test_kms_accepts_compact_number_commands(self):
        async def exercise():
            async def fake_names():
                return ["Actor One", "Actor Two", "Actor Three"]

            self.adapter._fetch_kms_names = fake_names
            await self.adapter._dispatch(FakeUser(), "kms", [])
            await self.adapter.on_chat(FakeUser(), "!kiss1")
            self.assertEqual(self.adapter.kms_round, 1)
            await self.adapter.on_chat(FakeUser(), "!marry1")
            self.assertEqual(self.adapter.kms_round, 2)
            await self.adapter.on_chat(FakeUser(), "!kill1")
            self.assertFalse(self.adapter.kms_active)
            self.assertTrue(any("KISS MARRY KILL" in args[0] for args, _ in self.adapter.highrise.chats))

        asyncio.run(exercise())

    def test_social_commands_have_distinct_three_stage_sequences(self):
        async def exercise():
            original_sleep = bot.asyncio.sleep

            async def fast_sleep(_seconds):
                return None

            bot.asyncio.sleep = fast_sleep
            try:
                for command in ("punch", "slap", "kiss", "hug"):
                    self.adapter.highrise.chats.clear()
                    response = await self.adapter._dispatch(
                        FakeUser(), command, ["@Target"]
                    )
                    self.assertIsNone(response)
                    messages = [args[0] for args, _kwargs in self.adapter.highrise.chats]
                    self.assertEqual(len(messages), 3)
                    self.assertNotEqual(messages[0], messages[1])
                    self.assertNotEqual(messages[1], messages[2])
            finally:
                bot.asyncio.sleep = original_sleep

        asyncio.run(exercise())

    def test_outfit_commands_apply_inventory_items(self):
        async def exercise():
            applied = []
            base_items = [
                bot.Item(
                    type="clothing",
                    amount=1,
                    id=item_id,
                    account_bound=False,
                    active_palette=27 if item_id == "body-flesh" else 0,
                )
                for item_id in bot.BASE_ITEM_IDS
            ]
            bot.BASE_ITEMS = base_items

            async def fake_inventory():
                return type(
                    "Inventory",
                    (),
                    {"items": base_items + bot.OUTFITS[1]["items"]},
                )()

            async def fake_set_outfit(items):
                applied.append(items)

            self.adapter.highrise.get_inventory = fake_inventory
            self.adapter.highrise.set_outfit = fake_set_outfit
            response = await self.adapter._dispatch(FakeUser(), "outfit", ["1"])
            self.assertEqual(response, "👕 Outfit changed: **Casual**!")
            self.assertEqual(applied[0], base_items + bot.OUTFITS[1]["items"])

        asyncio.run(exercise())

    def test_outfit_definitions_include_required_item_types(self):
        for outfit in bot.OUTFITS.values():
            ids = {item.id for item in outfit["items"]}
            self.assertTrue(any(item.id.startswith("shirt") for item in outfit["items"]))
            self.assertTrue(any(item.id.startswith("pants") for item in outfit["items"]))
        self.assertEqual(
            set(bot.BASE_ITEM_IDS),
            {
                "body-flesh",
                "eye-n_basic2018malesquaresleepy",
                "eyebrow-n_basic2018newbrows07",
                "nose-n_basic2018newnose05",
                "mouth-basic2018chippermouth",
                "hair_front-n_malenew05",
                "hair_back-n_malenew05",
                "freckle-n_basic2018freckle04",
            },
        )

    def test_oneword_accepts_letter_answers_and_skip(self):
        async def exercise():
            self.adapter.oneword_categories = ["animal", "country"]
            self.adapter.oneword_max_rounds = 2
            self.adapter.oneword_active = True
            self.adapter.oneword_player = FakeUser.id
            self.adapter.oneword_letter = "B"
            self.adapter.oneword_round = 0
            self.adapter.oneword_score = 0
            await self.adapter._dispatch(FakeUser(), "oneword", ["bear"])
            self.assertEqual(self.adapter.oneword_score, 1)
            self.assertEqual(self.adapter.oneword_round, 1)
            await self.adapter._dispatch(FakeUser(), "skip", [])
            self.assertFalse(self.adapter.oneword_active)
            self.assertIn("ONE WORD COMPLETE", self.adapter.highrise.chats[-1][0][0])

        asyncio.run(exercise())

    def test_21_actions_use_shared_table(self):
        async def exercise():
            self.adapter.blackjack.active = True
            self.adapter.blackjack.round_active = True
            self.adapter.blackjack.players[FakeUser.id] = {
                "hand": [10, 5],
                "total": 15,
                "done": False,
            }
            self.adapter.blackjack.dealer_hand = [10, 6]
            self.adapter.blackjack.dealer_total = 16
            response = await self.adapter._dispatch(
                FakeUser(), "21", ["stand"]
            )
            self.assertIsNone(response)
            self.assertTrue(self.adapter.blackjack.players[FakeUser.id]["done"])

        asyncio.run(exercise())

    def test_standalone_21_commands_and_context_help(self):
        async def exercise():
            response = await self.adapter._dispatch(FakeUser(), "hit", [])
            self.assertIsNone(response)
            self.assertIn("No active game", self.adapter.highrise.whispers[-1][0][1])

            response = await self.adapter._dispatch(FakeUser(), "help", ["21"])
            self.assertIsNone(response)
            self.assertIn("📖 **!21**", self.adapter.highrise.whispers[-1][0][1])
            self.assertIn("Same as !play 21", self.adapter.highrise.whispers[-1][0][1])

            await self.adapter._dispatch(FakeUser(), "help", ["bal"])
            self.assertIn("📖 **!bal**", self.adapter.highrise.whispers[-1][0][1])
            self.assertIn("Same as !balance", self.adapter.highrise.whispers[-1][0][1])

            await self.adapter._dispatch(FakeUser(), "help", ["teleport"])
            self.assertIn("📖 **!tele**", self.adapter.highrise.whispers[-1][0][1])

            await self.adapter._dispatch(FakeUser(), "help", ["notacommand"])
            self.assertEqual(
                self.adapter.highrise.whispers[-1][0][1],
                "❌ Unknown command. Type !help to see all commands.",
            )

        asyncio.run(exercise())

    def test_21_join_window_accepts_join_and_rejects_late_join(self):
        async def exercise():
            await self.adapter._dispatch(FakeUser(), "play", ["21"])
            self.assertTrue(self.adapter.blackjack.active)
            self.assertFalse(self.adapter.blackjack.round_active)

            joiner = type("Joiner", (), {"id": "target-id", "username": "Target"})()
            await self.adapter._dispatch(joiner, "join", [])
            self.assertIn("target-id", self.adapter.blackjack.players)

            self.adapter.blackjack.round_active = True
            await self.adapter.cmd_join_21(
                type("Late", (), {"id": "target-two", "username": "Second"})(),
                [],
            )
            self.assertIn("Too late to join", self.adapter.highrise.whispers[-1][0][1])

        async def fast_sleep(_seconds):
            return None

        original_sleep = bot.asyncio.sleep
        bot.asyncio.sleep = fast_sleep
        try:
            asyncio.run(exercise())
        finally:
            bot.asyncio.sleep = original_sleep

    def test_setowner_persists_config_for_owner_transfer(self):
        async def exercise():
            original_owner = bot.CONFIG.get("owner_id")
            config_path = bot.CONFIG_PATH
            with open(config_path, "r", encoding="utf-8") as config_file:
                original_config = config_file.read()
            try:
                bot.CONFIG["owner_id"] = FakeUser.id
                response = await self.adapter._dispatch(
                    FakeUser(), "setowner", ["@Target"]
                )
                self.assertIsNone(response)
                self.assertEqual(self.adapter.db.get_role("target-id"), "owner")
                with open(config_path, "r", encoding="utf-8") as config_file:
                    self.assertEqual(
                        bot.json.load(config_file)["owner_id"], "target-id"
                    )
            finally:
                bot.CONFIG["owner_id"] = original_owner
                with open(config_path, "w", encoding="utf-8") as config_file:
                    config_file.write(original_config)

        asyncio.run(exercise())

    def test_setowner_first_run_claims_self(self):
        async def exercise():
            with open(bot.CONFIG_PATH, "r", encoding="utf-8") as config_file:
                original_config = config_file.read()
            original_owner = bot.CONFIG.get("owner_id")
            try:
                bot.CONFIG["owner_id"] = ""
                response = await self.adapter._dispatch(
                    FakeUser(), "setowner", []
                )
                self.assertIsNone(response)
                self.assertEqual(bot.CONFIG["owner_id"], FakeUser.id)
                self.assertEqual(self.adapter.db.get_role(FakeUser.id), "owner")
            finally:
                bot.CONFIG["owner_id"] = original_owner
                with open(bot.CONFIG_PATH, "w", encoding="utf-8") as config_file:
                    config_file.write(original_config)

        asyncio.run(exercise())

    def test_every_emote_dispatches(self):
        async def exercise():
            for emote_name in bot.ALL_EMOTE_NAMES:
                await self.adapter.on_chat(FakeUser(), f"!emote {emote_name}")
            self.adapter.app.emotes.stop_loop(FakeUser.id)
            await asyncio.sleep(0)

        asyncio.run(exercise())

    def test_give_uses_internal_coins_without_payment_message(self):
        async def exercise():
            response = await self.adapter._dispatch(FakeUser(), "balance", [])
            self.assertIn("coins", response)
            response = await self.adapter._dispatch(
                FakeUser(), "give", ["another-user", "10"]
            )
            self.assertIn("gave 10 coins", response)
            self.assertNotIn("payment", response.casefold())

        asyncio.run(exercise())

    def test_mention_target_performs_emote(self):
        async def exercise():
            await self.adapter.on_chat(FakeUser(), "!ghostfloat @Target")
            await self.adapter.on_chat(FakeUser(), "!emote wave @Target")
            self.assertEqual(
                self.adapter.highrise.emotes,
                [
                    (("emote-ghost-idle",), {"target_user_id": "target-id"}),
                    (("emote-wave",), {"target_user_id": "target-id"}),
                ],
            )

        asyncio.run(exercise())

    def test_plain_emote_name_targets_the_user_who_said_it(self):
        async def exercise():
            await self.adapter.on_chat(FakeUser(), "ghostfloat")
            self.assertEqual(
                self.adapter.highrise.emotes[0],
                (("emote-ghost-idle",), {"target_user_id": "test-user"}),
            )

        asyncio.run(exercise())

    def test_errors_are_whispered_and_public_emotes_are_chatted(self):
        async def exercise():
            await self.adapter.on_chat(FakeUser(), "!notacommand")
            await self.adapter.on_chat(FakeUser(), "!wave")
            self.assertTrue(self.adapter.highrise.whispers)
            self.assertEqual(
                self.adapter.highrise.whispers[-1][0][0],
                FakeUser.id,
            )
            self.assertTrue(
                any("did: wave" in call[0][0]
                    for call in self.adapter.highrise.chats)
            )

        asyncio.run(exercise())

    def test_teleport_commands_create_set_and_move_users(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "admin")
            response = await self.adapter._dispatch(
                FakeUser(), "create", ["tele", "lobby", "4", "5", "6"]
            )
            self.assertIn("created", response)
            response = await self.adapter._dispatch(FakeUser(), "setpos", ["spawn"])
            self.assertIn("set at", response)
            response = await self.adapter._dispatch(FakeUser(), "tele", ["spawn"])
            self.assertIn("Teleported", response)
            self.assertEqual(self.adapter.highrise.teleport_call[0], FakeUser.id)
            self.adapter.db.set_role(FakeUser.id, "mod")
            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["@Target", "lobby"]
            )
            self.assertIn("target-id", self.adapter.highrise.teleport_call[0])

        asyncio.run(exercise())

    def test_tele_coordinate_and_bring_forms_use_permissions(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "admin")
            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["10.5", "0", "-3"]
            )
            self.assertIn("Teleported to (10.5, 0.0, -3.0)", response)
            self.assertEqual(self.adapter.highrise.teleport_call[0], FakeUser.id)

            self.adapter.db.set_role(FakeUser.id, "mod")
            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["@Target"]
            )
            self.assertIn("Brought Target to you", response)
            self.assertEqual(self.adapter.highrise.teleport_call[0], "target-id")

            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["@Target", "1", "4", "3"]
            )
            self.assertIn("Co-Owner", response)

            self.adapter.db.set_role(FakeUser.id, "coowner")
            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["@Target", "1", "4", "3"]
            )
            self.assertIn("Teleported Target to (1.0, 4.0, 3.0)", response)
            self.assertEqual(self.adapter.highrise.teleport_call[0], "target-id")

        asyncio.run(exercise())

    def test_seniormod_can_teleport_lower_ranked_target_to_named_teleport(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "seniormod")
            self.adapter.tele_data = {
                "user_ranks": {"target": "guest"},
                "teleports": {
                    "staffroom": {"x": 10.0, "y": 20.0, "z": 30.0}
                },
                "tele_ranks": {"staffroom": "admin"},
            }

            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["@Target", "staffroom"]
            )

            self.assertIn("Teleported Target to staffroom", response)
            self.assertEqual(self.adapter.highrise.teleport_call[0], "target-id")
            position = self.adapter.highrise.teleport_call[1]
            self.assertEqual((position.x, position.y, position.z), (10.0, 20.0, 30.0))

        asyncio.run(exercise())

    def test_mod_cannot_teleport_lower_ranked_target_to_named_teleport(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "mod")
            self.adapter.tele_data = {
                "user_ranks": {"target": "guest"},
                "teleports": {
                    "staffroom": {"x": 10.0, "y": 20.0, "z": 30.0}
                },
                "tele_ranks": {"staffroom": "admin"},
            }

            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["@Target", "staffroom"]
            )

            self.assertIn("requires rank admin", response)
            self.assertFalse(hasattr(self.adapter.highrise, "teleport_call"))

        asyncio.run(exercise())

    def test_named_tele_create_list_and_remove_permissions(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "admin")
            self.adapter.db.delete_tele_point("dancefloor_test")
            response = await self.adapter._dispatch(
                FakeUser(), "create", ["tele", "dancefloor_test"]
            )
            self.assertIn("created", response)
            self.assertEqual(
                self.adapter.db.get_tele_point("dancefloor_test"),
                (1.0, 2.0, 3.0),
            )

            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["list"]
            )
            self.assertIn("dancefloor_test", response)
            response = await self.adapter._dispatch(
                FakeUser(), "tele", ["dancefloor_test"]
            )
            self.assertIn("Teleported to dancefloor_test", response)

            response = await self.adapter._dispatch(
                FakeUser(), "remove", ["tele", "dancefloor_test"]
            )
            self.assertIn("Co-Owner", response)
            self.adapter.db.set_role(FakeUser.id, "coowner")
            response = await self.adapter._dispatch(
                FakeUser(), "remove", ["tele", "dancefloor_test"]
            )
            self.assertIn("removed", response)
            self.assertIsNone(self.adapter.db.get_tele_point("dancefloor_test"))

        asyncio.run(exercise())

    def test_role_management_commands(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "admin")
            response = await self.adapter._dispatch(
                FakeUser(), "give", ["@Target", "vip"]
            )
            self.assertIn("now vip", response)
            self.assertEqual(self.adapter.db.get_role("target-id"), "vip")
            response = await self.adapter._dispatch(
                FakeUser(), "give", ["@Target", "@Second", "vip"]
            )
            self.assertIn("Target, Second are now vip", response)
            self.assertEqual(self.adapter.db.get_role("target-two"), "vip")
            response = await self.adapter._dispatch(
                FakeUser(), "whois", ["@Target"]
            )
            self.assertIn("Role: vip", response)
            response = await self.adapter._dispatch(
                FakeUser(), "remove", ["@Target", "vip"]
            )
            self.assertIn("now guest", response)

        asyncio.run(exercise())

    def test_configured_owner_is_restored_on_startup(self):
        original_owner = bot.CONFIG.get("owner_id")
        try:
            bot.CONFIG["owner_id"] = "configured-owner"
            adapter = bot.Bot()
            self.assertEqual(adapter.db.get_role("configured-owner"), "owner")
            adapter.db.conn.execute(
                "DELETE FROM users WHERE user_id=?", ("configured-owner",)
            )
            adapter.db.conn.commit()
            adapter.db.conn.close()
        finally:
            if original_owner is None:
                bot.CONFIG.pop("owner_id", None)
            else:
                bot.CONFIG["owner_id"] = original_owner

    def test_configured_owner_has_full_access_and_cannot_be_changed(self):
        original_owner = bot.CONFIG.get("owner_id")
        try:
            bot.CONFIG["owner_id"] = "configured-owner"
            adapter = bot.Bot()
            adapter.highrise = FakeHighrise()
            adapter.app.highrise = adapter.highrise
            adapter.db.set_role(FakeUser.id, "admin")
            self.assertTrue(adapter.has_permission("configured-owner", "coowner"))
            owner_user = type(
                "ConfiguredOwner", (), {"id": "configured-owner", "username": "ConfiguredOwner"}
            )()
            response = asyncio.run(
                adapter._dispatch(
                    owner_user, "give", ["@Target", "vip"]
                )
            )
            self.assertIn("now vip", response)
            response = asyncio.run(
                adapter._dispatch(
                    FakeUser(), "give", ["@configured-owner", "guest"]
                )
            )
            self.assertIn("Cannot change", response)
            response = asyncio.run(
                adapter._dispatch(
                    FakeUser(), "remove", ["@configured-owner", "guest"]
                )
            )
            self.assertIn("Cannot change", response)
            adapter.db.conn.execute(
                "DELETE FROM users WHERE user_id=?", ("configured-owner",)
            )
            adapter.db.conn.commit()
            adapter.db.conn.close()
        finally:
            if original_owner is None:
                bot.CONFIG.pop("owner_id", None)
            else:
                bot.CONFIG["owner_id"] = original_owner

    def test_single_owner_is_enforced_across_database(self):
        original_owner = bot.CONFIG.get("owner_id")
        try:
            bot.CONFIG["owner_id"] = "configured-owner"
            adapter = bot.Bot()
            adapter.db.upsert_user("stale-owner")
            adapter.db.set_role("stale-owner", "owner")
            adapter.db.upsert_user("other-user")
            adapter.db.set_role("other-user", "owner")
            adapter._restore_owner()
            self.assertEqual(adapter.db.get_role("stale-owner"), "guest")
            self.assertEqual(adapter.db.get_role("other-user"), "guest")
            self.assertEqual(adapter.db.get_role("configured-owner"), "owner")
        finally:
            if original_owner is None:
                bot.CONFIG.pop("owner_id", None)
            else:
                bot.CONFIG["owner_id"] = original_owner

    def test_grab_telecord_and_mypos(self):
        async def exercise():
            self.adapter.db.set_role(FakeUser.id, "vip")
            self.adapter.db.set_role("target-id", "guest")
            self.adapter.db.set_role("target-two", "guest")
            response = await self.adapter._dispatch(
                FakeUser(), "grab", ["@Target", "@Second"]
            )
            self.assertIn("Grabbed: Target, Second", response)
            self.assertEqual(
                [call[0] for call in self.adapter.highrise.teleport_calls],
                ["target-id", "target-two"],
            )
            response = await self.adapter._dispatch(
                FakeUser(), "bring", ["@Target", "@Second"]
            )
            self.assertIn("Brought: Target, Second", response)
            self.assertEqual(len(self.adapter.highrise.teleport_calls), 4)
            self.adapter.db.set_role(FakeUser.id, "mod")
            response = await self.adapter._dispatch(
                FakeUser(), "telecord", ["10.5", "0", "-3"]
            )
            self.assertIn("10.5", response)
            self.assertEqual(self.adapter.highrise.teleport_call[0], FakeUser.id)
            response = await self.adapter._dispatch(FakeUser(), "mypos", [])
            self.assertIn("1.0", response)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()