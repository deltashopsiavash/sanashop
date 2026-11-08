import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-invalid-token")
os.environ.setdefault("TELEGRAM_OWNER_ID", "111")

import external_bot as core
import external_bot_v10 as v10
import external_bot_v15 as v15
import external_bot_v16 as v16


def update(uid, data):
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=uid), data=data,
        answer=AsyncMock(), edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query), SimpleNamespace(user_data={})


def callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]


class MultiSiteNumberedAndFAQTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.one = {"id": 1, "name": "فروشگاه الف", "api_key": "secret-one"}
        self.two = {"id": 2, "name": "فروشگاه ب", "api_key": "secret-two"}
        self.calls = []
        async def api(site, action, payload=None, **kwargs):
            self.calls.append((site["id"], action, payload))
            if action == "ping":
                return {"site": {"capabilities": ["product_options_v22", "faq_edit_v22"]}}
            if action == "product_options_list":
                return {"data": {
                    "product_name": "نیم ست", "options": [
                        {"id": 91, "number": 3, "name": "انگشتر", "label": "محصول شماره 3 — انگشتر",
                         "code": "SNA-TEST-03", "price": 120000, "is_available": False}
                    ],
                }}
            if action == "faq_get":
                return {"data": {"body": "سؤال: ارسال؟\nجواب: پست", "title": "سؤالات متداول"}}
            if action == "product_detail":
                return {"data": {
                    "id": 11, "name": "نیم ست", "sku": "SNA-TEST",
                    "price": 200000, "base_price": 200000,
                    "effective_price": 200000, "stock": 10,
                    "is_active": True,
                }}
            return {"ok": True, "data": {"id": 91}}
        for p in (
            patch.object(core, "can_access", side_effect=lambda uid, sid: (
                uid == 111 or (uid == 222 and sid == 1) or (uid == 333 and sid == 2)
            )),
            patch.object(core, "get_site", side_effect=lambda sid: {1: self.one, 2: self.two}.get(int(sid))),
            patch.object(core, "api", side_effect=api),
        ):
            p.start()
            self.addCleanup(p.stop)

    async def test_live_product_menu_has_numbered_options(self):
        q = SimpleNamespace(edit_message_text=AsyncMock())
        await v15._show_product(q, self.one, 1, 11)
        markup = q.edit_message_text.await_args.kwargs["reply_markup"]
        self.assertIn("opts_v22:1:11", callbacks(markup))

    async def test_settings_menu_has_faq_editor(self):
        markup = v10._settings_keyboard(1, {})
        self.assertIn("faq_v22:1", callbacks(markup))

    async def test_unauthorized_manager_cannot_open_other_site_options(self):
        u, ctx = update(222, "opts_v22:2:11")
        await v16.callback(u, ctx)
        self.assertEqual(self.calls, [])
        u.callback_query.answer.assert_awaited()

    async def test_unavailable_option_shows_in_manager_list(self):
        u, ctx = update(333, "opts_v22:2:11")
        await v16.callback(u, ctx)
        markup = u.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        self.assertIn("opt_item_v22:2:11:91", callbacks(markup))
        self.assertEqual([x[0] for x in self.calls], [2, 2])

    async def test_manager_can_toggle_option_for_only_own_site(self):
        u, ctx = update(222, "opt_switch_v22:1:11:91")
        await v16.callback(u, ctx)
        self.assertTrue(all(x[0] == 1 for x in self.calls))
        updates = [x for x in self.calls if x[1] == "product_options_update"]
        self.assertEqual(updates[0][2]["is_available"], True)
        self.assertEqual(updates[0][2]["option_id"], 91)

    async def test_add_option_from_text_uses_selected_site_only(self):
        u, ctx = update(333, "opt_add_v22:2:11")
        await v16.callback(u, ctx)
        msg = SimpleNamespace(text="2 | 95000 | دستبند", reply_text=AsyncMock())
        await v16.message(SimpleNamespace(effective_user=SimpleNamespace(id=333), message=msg), ctx)
        payloads = [x for x in self.calls if x[1] == "product_options_add"]
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0][0], 2)
        self.assertEqual(payloads[0][2]["price"], 95000)
        self.assertEqual(payloads[0][2]["number"], 2)

    async def test_faq_per_site_append_and_replace(self):
        u, ctx = update(222, "faq_append_v22:1")
        await v16.callback(u, ctx)
        msg = SimpleNamespace(text="سؤال: مرجوعی؟\nجواب: طبق قوانین", reply_text=AsyncMock())
        await v16.message(SimpleNamespace(effective_user=SimpleNamespace(id=222), message=msg), ctx)
        written = [x for x in self.calls if x[1] == "faq_set"]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0][0], 1)
        self.assertIn("سؤال: ارسال؟", written[0][2]["body"])
        self.assertIn("سؤال: مرجوعی؟", written[0][2]["body"])

    async def test_changed_site_during_text_flow_is_refused(self):
        context = SimpleNamespace(user_data={
            "flow": "v22_option_add", "site_id": 2, "product_id": 11,
        })
        msg = SimpleNamespace(text="4 | 80000 | انگشتر", reply_text=AsyncMock())
        await v16.message(SimpleNamespace(effective_user=SimpleNamespace(id=222), message=msg), context)
        self.assertFalse([x for x in self.calls if x[1] == "product_options_add"])
        self.assertEqual(context.user_data, {})


if __name__ == "__main__":
    unittest.main()
