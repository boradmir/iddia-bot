import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
import control


class ControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "control.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_is_empty(self):
        self.assertEqual(control.load(self.path), {})

    def test_load_broken_is_empty(self):
        open(self.path, "w").write("{bozuk")
        self.assertEqual(control.load(self.path), {})

    def test_save_and_load_roundtrip(self):
        d = {}
        control.set_post(d, "2026-10-31", 3255613, at="16:30")
        control.save(d, self.path)
        back = control.load(self.path)
        self.assertEqual(back["posts"]["2026-10-31:3255613"]["at"], "16:30")
        self.assertIn("updated", back)

    def test_parse_hm(self):
        self.assertEqual(control.parse_hm("16:30"), (16, 30))
        self.assertIsNone(control.parse_hm("saat"))
        self.assertIsNone(control.parse_hm("25:00"))
        self.assertIsNone(control.parse_hm(""))

    def test_pause(self):
        d = {}
        now = datetime(2026, 10, 31, 12, 0, tzinfo=control.TR)
        self.assertFalse(control.is_paused(d, now))
        control.set_pause(d, now + timedelta(hours=2))
        self.assertTrue(control.is_paused(d, now))
        self.assertFalse(control.is_paused(d, now + timedelta(hours=3)))
        control.set_pause(d, None)
        self.assertFalse(control.is_paused(d, now))
        d["paused_until"] = "tarih değil"
        self.assertFalse(control.is_paused(d, now))

    def test_post_skip_and_note(self):
        d = {}
        control.set_post(d, "2026-10-31", 1, skip=True, note="panelden")
        self.assertTrue(control.post(d, "2026-10-31", 1)["skip"])
        control.set_post(d, "2026-10-31", 1, skip=False)
        self.assertFalse(control.post(d, "2026-10-31", 1)["skip"])
        self.assertEqual(control.post(d, "2026-10-31", 1)["note"], "panelden")
        self.assertEqual(control.post(d, "2026-10-31", 2), {})

    def test_story_skip(self):
        d = {}
        self.assertFalse(control.story_skip(d, "2026-10-31", 5))
        control.set_story_skip(d, "2026-10-31", 5, True)
        self.assertTrue(control.story_skip(d, "2026-10-31", 5))
        control.set_story_skip(d, "2026-10-31", 5, False)
        self.assertFalse(control.story_skip(d, "2026-10-31", 5))

    def test_reels(self):
        d = {}
        self.assertEqual(control.reels(d, "2026-10-31"), {})
        control.set_reels(d, "2026-10-31", code=3255613, at="12:00", status="planned")
        control.set_reels(d, "2026-10-31", status="ready", asset="reels-2026-10-31/reels_3255613.mp4")
        r = control.reels(d, "2026-10-31")
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["code"], 3255613)
        self.assertEqual(r["at"], "12:00")


def _m(hour, code=1, weekday_date=(2026, 10, 30)):   # 30.10.2026 Cuma; hour = TSİ başlama saati
    return {"start": datetime(*weekday_date, hour, 0, tzinfo=timezone.utc) - timedelta(hours=3), "code": code}


class PostSlotsTest(unittest.TestCase):
    def setUp(self):
        import instagram
        self.ig = instagram
        self.today = "2026-10-30"

    def test_default_first_slot_is_noon(self):
        slots = self.ig.post_slots([(None, _m(20), None, False)], self.today, ctrl={})
        self.assertEqual((slots[0].hour, slots[0].minute), (12, 0))

    def test_control_at_overrides(self):
        ctrl = {"posts": {"2026-10-30:1": {"at": "14:15"}}}
        slots = self.ig.post_slots([(None, _m(20), None, False)], self.today, ctrl=ctrl)
        self.assertEqual((slots[0].hour, slots[0].minute), (14, 15))

    def test_control_at_still_one_hour_before_kickoff(self):
        ctrl = {"posts": {"2026-10-30:1": {"at": "19:45"}}}
        slots = self.ig.post_slots([(None, _m(20), None, False)], self.today, ctrl=ctrl)
        self.assertEqual((slots[0].hour, slots[0].minute), (19, 0))

    def test_reels_time_from_control(self):
        ctrl = {"reels": {"2026-10-30": {"at": "12:30", "status": "ready"}}}
        slots = self.ig.post_slots([(None, _m(20), None, False)], self.today, ctrl=ctrl)
        self.assertEqual((slots[0].hour, slots[0].minute), (10, 30))   # reels 2 saat içinde → 2 saat öne

    def test_cancelled_reels_ignored(self):
        ctrl = {"reels": {"2026-10-30": {"at": "12:30", "status": "cancelled"}}}
        slots = self.ig.post_slots([(None, _m(20), None, False)], self.today, ctrl=ctrl)
        self.assertEqual((slots[0].hour, slots[0].minute), (12, 0))


class WatchBlockTest(unittest.TestCase):
    def test_story_blocked_reads_control(self):
        import watch
        tmp = tempfile.TemporaryDirectory(); path = os.path.join(tmp.name, "c.json")
        old = control.PATH; control.PATH = path
        try:
            m = {"start": datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc), "code": 7, "home": "A", "away": "B"}
            self.assertIsNone(watch.story_blocked(m))
            d = {}; control.set_story_skip(d, "2026-10-31", 7, True); control.save(d, path)
            self.assertEqual(watch.story_blocked(m), "story atlandı (panel)")
            d = {}; control.set_pause(d, datetime(2099, 1, 1, tzinfo=control.TR)); control.save(d, path)
            self.assertEqual(watch.story_blocked(m), "duraklatıldı (panel)")
        finally:
            control.PATH = old; tmp.cleanup()


class ReelsDueTest(unittest.TestCase):
    def test_not_ready(self):
        import keeper
        now = datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(keeper.reels_due({"status": "planned", "asset": "x/y.mp4", "at": "12:00"}, now), (False, None))
        self.assertEqual(keeper.reels_due({}, now), (False, None))

    def test_ready_waiting(self):
        import keeper
        now = datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc)   # 11:00 TSİ
        self.assertEqual(keeper.reels_due({"status": "ready", "asset": "x/y.mp4", "at": "12:00"}, now), (False, (9, 0)))

    def test_ready_due(self):
        import keeper
        now = datetime(2026, 10, 31, 9, 1, tzinfo=timezone.utc)   # 12:01 TSİ
        self.assertEqual(keeper.reels_due({"status": "ready", "asset": "x/y.mp4", "at": "12:00"}, now), (True, None))

    def test_ready_no_time_is_due_now(self):
        import keeper
        now = datetime(2026, 10, 31, 9, 1, tzinfo=timezone.utc)
        self.assertEqual(keeper.reels_due({"status": "ready", "asset": "x/y.mp4"}, now), (True, None))


class ActionsApplyTest(unittest.TestCase):
    def test_set_time_and_clear(self):
        from panel import actions
        d, msg = actions.apply({}, {"action": "set_time", "code": 5, "at": "16:30"}, "2026-10-31")
        self.assertEqual(control.post(d, "2026-10-31", 5)["at"], "16:30")
        d, msg = actions.apply(d, {"action": "set_time", "code": 5, "at": ""}, "2026-10-31")
        self.assertNotIn("at", control.post(d, "2026-10-31", 5))

    def test_bad_time_raises(self):
        from panel import actions
        with self.assertRaises(ValueError):
            actions.apply({}, {"action": "set_time", "code": 5, "at": "99:99"}, "2026-10-31")

    def test_skip_and_story_skip(self):
        from panel import actions
        d, _ = actions.apply({}, {"action": "skip", "code": 5, "skip": True}, "2026-10-31")
        self.assertTrue(control.post(d, "2026-10-31", 5)["skip"])
        d, _ = actions.apply(d, {"action": "story_skip", "code": 5, "skip": True}, "2026-10-31")
        self.assertTrue(control.story_skip(d, "2026-10-31", 5))

    def test_pause_today_and_clear(self):
        from panel import actions
        d, _ = actions.apply({}, {"action": "pause", "until": "today"}, "2026-10-31")
        self.assertTrue(d["paused_until"].startswith("2026-10-31T23:59"))
        d, _ = actions.apply(d, {"action": "pause", "until": None}, "2026-10-31")
        self.assertIsNone(d["paused_until"])

    def test_unknown_action(self):
        from panel import actions
        with self.assertRaises(ValueError):
            actions.apply({}, {"action": "uçur"}, "2026-10-31")


if __name__ == "__main__":
    unittest.main()
