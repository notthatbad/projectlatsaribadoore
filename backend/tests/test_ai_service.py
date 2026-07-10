import unittest
import importlib.util


spec = importlib.util.spec_from_file_location('ai_service', 'backend/app/ai_service.py')
ai_service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_service)


class BuildAIPromptTests(unittest.TestCase):
    def test_build_ai_prompt_respects_offensive_limits(self):
        prompt = ai_service.build_ai_prompt('Harga BBM', 'kontra narasi', 'Offensive', 12)
        self.assertIn('12', prompt)
        self.assertIn('maksimal 1', prompt.lower())
        self.assertIn('kata kasar', prompt.lower())
        self.assertIn('visual_prompt', prompt)
        self.assertIn('komentar', prompt)


if __name__ == '__main__':
    unittest.main()
