"""A button that sets a flag and starts nothing is not a button.

The room now refuses to open a microphone unless the switch says he
turned it on — correct — and for one commit the switch did ONLY that. On
a machine where the listener is not already running, which is every
machine now that it does not start itself, pressing MIC would have
written a file and produced silence. He would press it, hear nothing,
and conclude the whole thing is broken. He would be right.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import ears, intercom, journal


class ButtonCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        for p in (mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl"),
                  mock.patch.object(ears, "_boot_id", return_value="boot-1")):
            p.start()
            self.addCleanup(p.stop)

    def press(self, started=True, detail="listener started"):
        with mock.patch.object(ears, "start_room",
                               return_value=(started, detail)) as start:
            said = intercom.execute_command({"kind": "mic_on"}, {},
                                            quote="pressed MIC")
        return said, start


class PressingItStartsListeningCase(ButtonCase):
    def test_the_switch_goes_on_AND_the_listener_starts(self):
        said, start = self.press()
        self.assertTrue(ears.listening())
        start.assert_called_once()
        self.assertIn("microphone is on", said)

    def test_a_listener_that_would_not_start_is_admitted_not_hidden(self):
        """The flag on and the process not is exactly what he needs told.

        Reporting "the microphone is on" when nothing is listening is
        the lie that costs him a conversation with an empty room.
        """
        said, _ = self.press(started=False,
                             detail="could not start the listener (OSError)")
        self.assertIn("could not start", said)
        self.assertIn("Nothing is listening", said)

    def test_turning_it_off_stops_the_listener_too(self):
        with mock.patch.object(ears, "start_room", return_value=(True, "ok")):
            intercom.execute_command({"kind": "mic_on"}, {}, quote="on")
        with mock.patch.object(ears, "stop_room",
                               return_value=(True, "stopped")) as stop:
            said = intercom.execute_command({"kind": "mic_off"}, {}, quote="off")
        stop.assert_called_once()
        self.assertFalse(ears.listening())
        self.assertIn("Nothing is listening", said)


class StartingTheRoomIsSafeCase(ButtonCase):
    def test_starting_twice_does_not_make_two_listeners(self):
        with mock.patch.object(ears, "room_is_running", return_value=True):
            started, detail = ears.start_room()
        self.assertTrue(started)
        self.assertIn("already", detail)

    def test_neither_start_nor_stop_ever_raises(self):
        """These run inside a command handler; an exception here would
        turn a button press into an error page."""
        with mock.patch("subprocess.Popen", side_effect=OSError("no exec")), \
             mock.patch.object(ears, "room_is_running", return_value=False):
            started, detail = ears.start_room()
        self.assertFalse(started)
        self.assertIn("could not start", detail)

        with mock.patch("subprocess.run", side_effect=OSError("no shell")):
            stopped, detail = ears.stop_room()
        self.assertFalse(stopped)
        self.assertIn("could not stop", detail)

    def test_asking_whether_it_is_running_never_raises(self):
        with mock.patch("subprocess.run", side_effect=OSError("no shell")):
            self.assertFalse(ears.room_is_running())


if __name__ == "__main__":
    unittest.main()
