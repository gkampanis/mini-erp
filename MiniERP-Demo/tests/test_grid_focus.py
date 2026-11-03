"""Exercise real fill orchestration against a synthetic Win32 grid/editor."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.infrastructure.ebs_adapter.adapter import FIELDS, WindowsAdapter


class GridFocusTests(unittest.TestCase):
    def run_grid(self, *, stuck=False, broad=False, foreign=False, lose_on_select=False,
                 lose_on_delete=False, wrong_root=False, no_focus=False, first_click=False):
        state = dict(cell='account', net_clicks=0, values={}, deleted=[])
        mapping = {field: (10 + i * 100, 50) for i, (field, _) in enumerate(FIELDS)}
        payload = dict(vat='000000008', invoice='TEST', date='21/10/2026', account='64.03', net='123,45')
        user = SimpleNamespace()
        user.GetForegroundWindow = Mock(return_value=100)
        user.GetAncestor = Mock(return_value=999 if wrong_root else 100)
        user.WindowFromPoint = Mock(return_value=200)
        def process(handle, result):
            result._obj.value = 88 if foreign and handle == 300 else 77
            return 12 if handle == 100 else 19
        user.GetWindowThreadProcessId = Mock(side_effect=process)
        def gui(thread, result):
            self.assertEqual(thread, 19)  # The grid is on a different GUI thread.
            result._obj.hwndFocus = 0 if no_focus else 300
            return 1
        user.GetGUIThreadInfo = Mock(side_effect=gui)
        def rect(handle, result):
            left = 300 if state['cell'] == 'account' else 400
            r = result._obj
            r.left, r.top, r.right, r.bottom = (0, 0, 600, 100) if broad else (left, 40, left + 40, 65)
            return 1
        user.GetWindowRect = Mock(side_effect=rect)
        def click(x, y):
            if x == 410:
                state['net_clicks'] += 1
                # The first click only dismisses the account editor/lookup.
                if state['net_clicks'] >= (1 if first_click else 2) and not stuck: state['cell'] = 'net'
        def hotkey(*keys):
            if lose_on_select and state['cell'] == 'net': state['cell'] = 'account'
        def press(key):
            if key == 'delete':
                state['deleted'].append(state['cell'])
                if lose_on_delete and state['cell'] == 'net': state['cell'] = 'account'
        def write(value, interval): state['values'][value] = state['cell']
        pg = SimpleNamespace(click=click, hotkey=hotkey, press=press, write=write, failSafeCheck=lambda: None)
        driver = WindowsAdapter.__new__(WindowsAdapter)
        driver.pg, driver.pid = pg, 77
        driver.sleep = lambda seconds: None
        driver.validate_target = lambda field, point: point
        self.state = state
        with patch.object(ctypes, 'windll', SimpleNamespace(user32=user), create=True):
            driver.fill(payload, mapping)
        return state

    def test_retry_moves_to_net_after_first_click_only_closes_account_editor(self):
        state = self.run_grid()
        self.assertEqual(state['values']['123,45'], 'net')
        self.assertEqual(state['values']['64.03'], 'account')

    def test_stuck_account_stops_before_net_clears_or_overwrites_it(self):
        with self.assertRaises(RuntimeError): self.run_grid(stuck=True)
        self.assertNotIn('123,45', self.state['values'])
        self.assertEqual(len(self.state['deleted']), 3)

    def test_shared_grid_rectangle_is_not_proof_of_active_net_cell(self):
        with self.assertRaises(RuntimeError): self.run_grid(broad=True)
        self.assertNotIn('123,45', self.state['values'])

    def test_foreign_focused_editor_is_rejected(self):
        with self.assertRaises(RuntimeError): self.run_grid(foreign=True)
        self.assertNotIn('123,45', self.state['values'])

    def test_focus_loss_after_select_all_stops_before_delete(self):
        with self.assertRaises(RuntimeError): self.run_grid(lose_on_select=True)
        self.assertNotIn('123,45', self.state['values'])
        self.assertEqual(len(self.state['deleted']), 3)

    def test_focus_loss_after_delete_stops_before_writing_amount(self):
        with self.assertRaises(RuntimeError): self.run_grid(lose_on_delete=True)
        self.assertNotIn('123,45', self.state['values'])

    def test_other_root_or_missing_focus_cannot_accept_the_amount(self):
        for options in (dict(wrong_root=True), dict(no_focus=True)):
            with self.subTest(options=options):
                with self.assertRaises(RuntimeError): self.run_grid(**options)
                self.assertNotIn('123,45', self.state['values'])

    def test_already_active_net_editor_does_not_receive_extra_clicks(self):
        state = self.run_grid(first_click=True)
        self.assertEqual(state['net_clicks'], 1)
        self.assertEqual(state['values']['123,45'], 'net')
