"""vision 模块纯逻辑单元测试。

覆盖 @ 引用解析、媒体类型推断、content parts 构建、read_image 文件校验，
不触网，仅使用 stdlib unittest。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_vision -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.chater import vision


class TestExtractImages(unittest.TestCase):
    """验证 @ 图片引用解析。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.img = os.path.join(self._tmp.name, "shot.png")
        with open(self.img, "wb") as f:
            f.write(b"\x89PNG\r\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_bare_path(self):
        clean, images = vision.extract_images(f"看看 @{self.img} 内容")
        self.assertEqual(images[0]["path"], os.path.realpath(self.img))
        self.assertEqual(images[0]["media_type"], "image/png")
        self.assertEqual(clean, "看看 内容")

    def test_quoted_path_with_spaces(self):
        spaced = os.path.join(self._tmp.name, "my photo.png")
        with open(spaced, "wb") as f:
            f.write(b"\x89PNG\r\n")
        clean, images = vision.extract_images(f'看看 @"{spaced}" 好吗')
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["path"], os.path.realpath(spaced))
        self.assertEqual(clean, "看看 好吗")

    def test_nonexistent_path_kept_as_text(self):
        text = "看看 @不存在路径.png 内容"
        clean, images = vision.extract_images(text)
        self.assertEqual(images, [])
        self.assertEqual(clean, text)

    def test_non_image_extension_kept_as_text(self):
        txt = os.path.join(self._tmp.name, "note.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write("hello")
        text = f"查看 @{txt}"
        clean, images = vision.extract_images(text)
        self.assertEqual(images, [])
        self.assertEqual(clean, text)

    def test_email_like_at_not_misdetected(self):
        text = "联系我 email@example.com"
        clean, images = vision.extract_images(text)
        self.assertEqual(images, [])
        self.assertEqual(clean, text)

    def test_multiple_images(self):
        second = os.path.join(self._tmp.name, "b.jpg")
        with open(second, "wb") as f:
            f.write(b"\xff\xd8")
        clean, images = vision.extract_images(f"@{self.img} 对比 @{second}")
        self.assertEqual(len(images), 2)
        self.assertEqual(clean, "对比")

    def test_no_images_returns_original(self):
        text = "普通消息，没有图片"
        clean, images = vision.extract_images(text)
        self.assertEqual(images, [])
        self.assertEqual(clean, text)


class TestCapability(unittest.TestCase):
    """验证模型能力查询。"""

    def test_vision_capable(self):
        with mock.patch.object(vision, "_get_model_meta",
                               return_value={"capabilities": ["vision"]}):
            self.assertTrue(vision.is_vision_capable("deepseek-flash"))

    def test_not_vision_capable(self):
        with mock.patch.object(vision, "_get_model_meta",
                               return_value={"capabilities": []}):
            self.assertFalse(vision.is_vision_capable("text-only"))

    def test_missing_metadata_not_capable(self):
        with mock.patch.object(vision, "_get_model_meta", return_value=None):
            self.assertFalse(vision.is_vision_capable("unknown"))

    def test_files_transport_flag(self):
        with mock.patch.object(vision, "_get_model_meta",
                               return_value={"vision_transport": "file"}):
            self.assertTrue(vision.use_files_transport("m"))
        with mock.patch.object(vision, "_get_model_meta", return_value={}):
            self.assertFalse(vision.use_files_transport("m"))


class TestBuildImageParts(unittest.TestCase):
    """验证 content parts 构建。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.img = os.path.join(self._tmp.name, "shot.png")
        with open(self.img, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        self.images = [{"path": self.img, "media_type": "image/png"}]

    def tearDown(self):
        self._tmp.cleanup()

    def test_base64_part(self):
        with mock.patch.object(vision, "use_files_transport", return_value=False):
            parts = vision.build_image_parts(self.images, client=None, model_name="m")
        self.assertEqual(parts[0]["type"], "image_url")
        url = parts[0]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))

    def test_file_part_with_fake_client(self):
        fake_file = mock.Mock(id="file-api-abc")
        fake_client = mock.Mock()
        fake_client.files.create.return_value = fake_file
        with mock.patch.object(vision, "use_files_transport", return_value=True):
            parts = vision.build_image_parts(self.images, client=fake_client, model_name="m")
        self.assertEqual(parts, [{"type": "file", "file_id": "file-api-abc"}])
        args, kwargs = fake_client.files.create.call_args
        self.assertEqual(kwargs.get("purpose"), "user_data")

    def test_file_upload_failure_falls_back_to_base64(self):
        fake_client = mock.Mock()
        fake_client.files.create.side_effect = RuntimeError("网络错误")
        with mock.patch.object(vision, "use_files_transport", return_value=True):
            parts = vision.build_image_parts(self.images, client=fake_client, model_name="m")
        self.assertEqual(parts[0]["type"], "image_url")

    def test_file_id_cache(self):
        fake_file = mock.Mock(id="file-api-xyz")
        fake_client = mock.Mock()
        fake_client.files.create.return_value = fake_file
        vision._file_id_cache.clear()
        try:
            with mock.patch.object(vision, "use_files_transport", return_value=True):
                vision.build_image_parts(self.images, client=fake_client, model_name="m")
                vision.build_image_parts(self.images, client=fake_client, model_name="m")
        finally:
            vision._file_id_cache.clear()
        self.assertEqual(fake_client.files.create.call_count, 1)


class TestReadImageFile(unittest.TestCase):
    """验证 read_image 工具的文件校验。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.img = os.path.join(self._tmp.name, "shot.png")
        with open(self.img, "wb") as f:
            f.write(b"\x89PNG\r\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_success(self):
        result = vision.read_image_file(self.img)
        self.assertTrue(result["success"])
        self.assertEqual(result["path"], os.path.realpath(self.img))
        self.assertEqual(result["media_type"], "image/png")
        # images 字段供 _run_tool_calls 通用注入合成消息
        self.assertEqual(result["images"],
                         [{"path": os.path.realpath(self.img), "media_type": "image/png"}])
        # 工具行灰色标签
        self.assertEqual(result["user_output"]["label"], "Image")
        self.assertEqual(result["user_output"]["parts"][0]["style"], "gray")

    def test_missing_path_arg(self):
        result = vision.read_image_file("")
        self.assertIn("error", result)
        # 失败同样带 user_output（红色标签），不再全文刷屏
        self.assertEqual(result["user_output"]["label"], "Image")
        self.assertEqual(result["user_output"]["parts"][0]["style"], "red")

    def test_file_not_found(self):
        result = vision.read_image_file(os.path.join(self._tmp.name, "nope.png"))
        self.assertIn("error", result)

    def test_unsupported_extension(self):
        txt = os.path.join(self._tmp.name, "a.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write("x")
        result = vision.read_image_file(txt)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
