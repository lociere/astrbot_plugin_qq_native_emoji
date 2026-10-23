import ast
import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_metadata_identifies_correct_platform_and_owner(self):
        meta = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "astrbot_plugin_qq_native_emoji")
        self.assertEqual(meta["author"], "lociere")
        self.assertEqual(meta["support_platforms"], ["aiocqhttp"])
        self.assertNotIn("qq_official", meta["support_platforms"])
        self.assertIn(meta["author"] + "/" + meta["name"], meta["repo"])

    def test_config_has_no_account_or_authentication_secret(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        for key in schema:
            self.assertNotIn("token", key)
            self.assertNotIn("password", key)
        self.assertEqual(schema["face_config_paths"]["default"], [])

    def test_llm_tool_docstrings_cover_signature(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        tools = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if not any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr == "llm_tool"
                for d in node.decorator_list
            ):
                continue
            tools.append(node.name)
            doc = ast.get_docstring(node)
            self.assertIn("Args:", doc)
            for arg in node.args.args[2:]:
                self.assertIn(arg.arg + "(", doc)
        self.assertEqual(set(tools), {"search_tool", "send_tool"})
