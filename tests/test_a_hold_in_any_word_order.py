"""The day and time may come before "my calendar" or after it."""
import unittest

from aletheia import voice


def held(said):
    c = (voice._interpret(said) or {}).get("command") or {}
    return c.get("kind"), c.get("title"), str(c.get("start", ""))[11:16]


class AHoldInAnyWordOrder(unittest.TestCase):
    def test_day_and_time_before_the_calendar(self):
        self.assertEqual(held("add lunch with dana friday at noon to my calendar"),
                         ("calendar_hold", "lunch with dana", "12:00"))

    def test_time_then_day(self):
        self.assertEqual(held("put dentist at 3 tomorrow on my calendar"),
                         ("calendar_hold", "dentist", "15:00"))

    def test_the_old_order_still_works(self):
        self.assertEqual(held("add dinner with sam on my calendar friday at 7"),
                         ("calendar_hold", "dinner with sam", "19:00"))

    def test_no_day_or_time_is_not_a_hold(self):
        self.assertNotEqual(held("add my trip to my calendar")[0], "calendar_hold")


if __name__ == "__main__":
    unittest.main()


class SearchTheWeb(unittest.TestCase):
    def test_search_the_web_is_research(self):
        for said, q in (("search the web for best tacos in denver", "best tacos in denver"),
                        ("google cheap flights to denver", "cheap flights to denver")):
            c = (voice._interpret(said) or {}).get("command") or {}
            self.assertEqual((c.get("kind"), c.get("question")), ("research", q))

    def test_a_file_search_is_still_a_file(self):
        c = (voice._interpret("search for my resume") or {}).get("command") or {}
        self.assertEqual(c.get("kind"), "file_find")


class TimersSayTheirNumber(unittest.TestCase):
    def text(self, said):
        return ((voice._interpret(said) or {}).get("command") or {}).get("text")

    def test_an_hour_is_one_hour(self):
        self.assertEqual(self.text("remind me in an hour"), "your 1-hour timer is up")

    def test_half_an_hour_is_thirty_minutes(self):
        self.assertEqual(self.text("remind me in half an hour"), "your 30-minute timer is up")
        self.assertEqual(self.text("set a timer for half an hour"), "your 30-minute timer is up")

    def test_his_number_word_stays(self):
        self.assertEqual(self.text("set a timer for ten minutes"), "your ten-minute timer is up")


class HowsMyDay(unittest.TestCase):
    def test_hows_my_day_look_is_the_plan(self):
        from aletheia import quick
        self.assertEqual(quick.match("how's my day look")[0], "plan_today")
        self.assertEqual(quick.match("how does today look")[0], "plan_today")
