"""Tests for gallery isolation between the independent SanaShop site panels."""
import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-invalid-token")
os.environ.setdefault("TELEGRAM_OWNER_ID", "111")

import external_bot as core
import external_bot_plus as plus
import external_bot_v16 as bot

SITES = {
    1: {"id": 1, "name": "فروشگاه اول", "base_url": "https://first.test", "api_key": "secret-one"},
    2: {"id": 2, "name": "فروشگاه دوم", "base_url": "https://second.test", "api_key": "secret-two"},
}
PRODUCTS = {
    1: [{"id": 101, "name": "دستبند", "sku": "SNA-001"}],
    2: [{"id": 202, "name": "گردنبند", "sku": "SNA-002"}],
}


def _update(user_id, data):
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        data=data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query), SimpleNamespace(user_data={})


def _button_data(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]


class MultiSiteGalleryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.queries = []
        self.permit = patch.object(
            core, "can_access", side_effect=lambda user, sid: (
                user == 111 or (user == 222 and sid == 1) or
                (user == 333 and sid == 2)
            ))
        self.lookup = patch.object(core, "get_site", side_effect=lambda sid: SITES.get(int(sid)))

        async def api(site, action, payload=None, **kwargs):
            self.queries.append((site["id"], action, payload))
            if action == "ping":
                return {"ok": True, "site": {
                    "name": site["name"], "capabilities": ["product_gallery_v17"]}}
            if action == "products":
                return {"ok": True, "data": PRODUCTS[site["id"]]}
            if action == "product_detail":
                if payload["id"] != PRODUCTS[site["id"]][0]["id"]:
                    raise ValueError("Wrong site's product")
                return {"ok": True, "data": {
                    "id": payload["id"], "sku": "TEST", "name": site["name"],
                    "base_price": 200000, "price": 200000,
                    "stock": 5, "is_active": True
                }}
            raise ValueError("Unexpected API call")

        self.api = patch.object(core, "api", side_effect=api)
        self.permit.start()
        self.lookup.start()
        self.api.start()
        self.addCleanup(self.permit.stop)
        self.addCleanup(self.lookup.stop)
        self.addCleanup(self.api.stop)

    async def test_telegram_token_not_logged_in_http_request_info(self):
        # httpx INFO logs include the full bot API URL with its secret token.
        self.assertGreaterEqual(logging.getLogger("httpx").getEffectiveLevel(), logging.WARNING)
        self.assertGreaterEqual(logging.getLogger("httpcore").getEffectiveLevel(), logging.WARNING)

    async def test_each_site_admin_panel_has_own_gallery_button(self):
        for site in SITES.values():
            data = _button_data(plus.enhanced_site_panel(site, 222))
            self.assertIn(f"galleries_v18:{site['id']}", data)
            self.assertNotIn(f"galleries_v18:{3 - site['id']}", data)

    async def test_first_admin_cannot_open_second_site_gallery(self):
        update, context = _update(222, "galleries_v18:2")
        await bot.callback(update, context)
        update.callback_query.answer.assert_awaited_once()
        self.assertEqual(self.queries, [])
        self.assertFalse(update.callback_query.edit_message_text.await_args_list)

    async def test_admin_gallery_list_stays_within_own_site(self):
        update, context = _update(222, "galleries_v18:1")
        await bot.callback(update, context)
        self.assertEqual([site_id for site_id, _, _ in self.queries], [1, 1])
        markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        callbacks = _button_data(markup)
        self.assertIn("prod_gallery_v17:1:101", callbacks)
        self.assertIn("site_info:1", callbacks)
        self.assertNotIn("prod_gallery_v17:2:202", callbacks)

    async def test_owner_can_select_second_site_without_cross_loading_first(self):
        update, context = _update(111, "galleries_v18:2")
        await bot.callback(update, context)
        self.assertEqual([site_id for site_id, _, _ in self.queries], [2, 2])
        markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        self.assertIn("prod_gallery_v17:2:202", _button_data(markup))

    async def test_product_menu_always_shows_gallery_button_on_live_v16(self):
        update, context = _update(333, "product:2:202")
        await bot.callback(update, context)
        self.assertEqual([site_id for site_id, _, _ in self.queries], [2])
        markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        self.assertIn("prod_gallery_v17:2:202", _button_data(markup))

    async def test_missing_gallery_api_reports_update_without_changing_site(self):
        async def old_site_api(site, action, payload=None, **kwargs):
            self.assertEqual(site["id"], 1)
            self.assertEqual(action, "ping")
            return {"ok": True, "site": {"version": 10}}
        with patch.object(core, "api", side_effect=old_site_api):
            update, context = _update(222, "galleries_v18:1")
            await bot.callback(update, context)
        message = update.callback_query.edit_message_text.await_args.args[0]
        self.assertIn("سایت انتخاب‌شده", message)
        self.assertIn("آپدیت", message)

    async def test_version_command_for_assigned_site_does_not_disclose_api_key(self):
        with patch.object(core, "is_authorized", return_value=True), patch.object(
            core, "assigned_site", return_value=SITES[1]
        ):
            message = SimpleNamespace(reply_text=AsyncMock())
            update = SimpleNamespace(effective_user=SimpleNamespace(id=222), message=message)
            await bot.version_command(update, SimpleNamespace())
        version_text = message.reply_text.await_args.args[0]
        self.assertIn("product-gallery-v18", version_text)
        self.assertIn("فروشگاه اول", version_text)
        self.assertNotIn("secret-one", version_text)


if __name__ == "__main__":
    unittest.main()
