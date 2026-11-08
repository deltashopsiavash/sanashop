import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-invalid-token")
os.environ.setdefault("TELEGRAM_OWNER_ID", "111")

import external_bot as core
import external_bot_colors as colors
import external_bot_v15 as v15
import external_bot_v16 as v16


def update(uid, data):
    q = SimpleNamespace(
        from_user=SimpleNamespace(id=uid),
        data=data, answer=AsyncMock(), edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(callback_query=q), SimpleNamespace(user_data={})


class ProductColorsMultiSiteBotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.one = {"id": 1, "name": "سایت اول"}
        self.two = {"id": 2, "name": "سایت دوم"}
        permits = patch.object(core, "can_access", side_effect=lambda uid, sid: (
            (uid == 101 and sid == 1) or (uid == 202 and sid == 2) or uid == 111
        ))
        lookup = patch.object(core, "get_site", side_effect=lambda sid: {
            1: self.one, 2: self.two
        }.get(int(sid)))
        async def api(site, action, payload=None, **kwargs):
            self.calls.append((site["id"], action, payload))
            if action == "ping":
                return {"site": {"capabilities": ["product_colors_v21"]}}
            if action == "product_colors_list":
                return {"data": {"product_id": 11, "product_name": "گردنبند", "colors": [
                    {"id": 9, "name": "مشکی", "hex_code": "#000000", "is_active": True}
                ]}}
            return {"ok": True, "data": {"id": 9}}
        api_patch = patch.object(core, "api", side_effect=api)
        for p in [permits, lookup, api_patch]:
            p.start()
            self.addCleanup(p.stop)

    async def test_color_button_visible_in_product_manager(self):
        q = SimpleNamespace(edit_message_text=AsyncMock())
        with patch.object(v15.core, "api", return_value={"data": {
            "id": 11, "name": "گردنبند", "sku": "SNA-11",
            "stock": 10, "is_active": True,
        }}):
            await v15._show_product(q, self.one, 1, 11)
        markup = q.edit_message_text.await_args.kwargs["reply_markup"]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("prod_colors_v21:1:11", callbacks)

    async def test_cannot_edit_another_site_color(self):
        u, ctx = update(101, "color_delete_confirm_v21:2:11:9")
        await v16.callback(u, ctx)
        self.assertEqual(self.calls, [])
        u.callback_query.answer.assert_awaited()

    async def test_manager_gets_only_selected_sites_colors(self):
        u, ctx = update(202, "prod_colors_v21:2:11")
        await v16.callback(u, ctx)
        self.assertEqual([r[0] for r in self.calls], [2, 2])
        markup = u.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("color_edit_v21:2:11:9", callbacks)
        self.assertFalse(any("color_edit_v21:1:" in x for x in callbacks))

    async def test_color_add_text_flow_cannot_switch_site(self):
        msg = SimpleNamespace(text="مشکی | #000000", reply_text=AsyncMock())
        upd = SimpleNamespace(effective_user=SimpleNamespace(id=101), message=msg)
        ctx = SimpleNamespace(user_data={
            "flow": "v21_color_add", "site_id": 2, "product_id": 11,
        })
        await v16.message(upd, ctx)
        self.assertEqual(self.calls, [])
        self.assertEqual(ctx.user_data, {})


if __name__ == "__main__":
    unittest.main()
