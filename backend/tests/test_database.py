import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import create_content_plan, create_topic, init_db, list_content_plans, list_topics


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(os.path.dirname(__file__), "test_data.sqlite3")
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        init_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_create_and_list_topics(self):
        topic_id = create_topic(self.db_path, "SEO", "tips seo")
        topics = list_topics(self.db_path)

        self.assertIsNotNone(topic_id)
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["title"], "SEO")
        self.assertEqual(topics[0]["search_query"], "tips seo")

    def test_create_content_plan_with_selected_topics(self):
        topic_one = create_topic(self.db_path, "TikTok", "cara viral")
        topic_two = create_topic(self.db_path, "Reels", "ide reels")

        plan_id = create_content_plan(
            self.db_path,
            date_value="2026-07-01",
            slot="pagi",
            selected_topic_ids=[topic_one, topic_two],
        )
        plans = list_content_plans(self.db_path)

        self.assertIsNotNone(plan_id)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["date_value"], "2026-07-01")
        self.assertEqual(plans[0]["slot"], "pagi")
        self.assertEqual(len(plans[0]["topics"]), 2)


if __name__ == "__main__":
    unittest.main()
