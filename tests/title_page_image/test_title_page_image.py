from pathlib import Path

import mdfusion.mdfusion as mdfusion


class _FakeHeaders:
    def get_content_type(self):
        return "image/jpeg"


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.headers = _FakeHeaders()

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_title_page_image_url_is_downloaded_and_included(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "chapter.md").write_text("# Chapter 1\n\nHello world.\n", encoding="utf-8")

    merged_md_dir = tmp_path / "merged"
    merged_md_dir.mkdir()
    out_pdf = tmp_path / "book.pdf"
    image_url = (
        "https://upload.wikimedia.org/wikipedia/commons/4/48/Angela_Merkel_2023.jpg"
    )
    image_bytes = b"fake-jpeg-bytes"
    captured = {}

    def fake_urlopen(request, timeout=10):
        assert request.full_url == image_url
        assert timeout == 10
        return _FakeResponse(image_bytes)

    def fake_spinner(cmd, out_pdf_arg, source_spans):
        captured["cmd"] = cmd
        captured["out_pdf"] = out_pdf_arg
        captured["source_spans"] = source_spans

    monkeypatch.setattr(mdfusion, "urlopen", fake_urlopen)
    monkeypatch.setattr(mdfusion, "run_pandoc_with_spinner", fake_spinner)
    monkeypatch.setattr(mdfusion.pypandoc, "get_pandoc_path", lambda: "pandoc")

    params = mdfusion.RunParams(
        root_dir=docs,
        output=str(out_pdf),
        merged_md=merged_md_dir,
        title_page=True,
        title="My Book",
        author="Jane Doe",
        title_page_image=image_url,
    )
    mdfusion.run(params)

    cmd = captured["cmd"]
    header_arg = next(arg for arg in cmd if arg.startswith("--include-in-header="))
    header_path = Path(header_arg.split("=", 1)[1])
    header_content = header_path.read_text(encoding="utf-8")

    downloaded_image = merged_md_dir / "title-page-image.jpg"
    assert downloaded_image.read_bytes() == image_bytes
    assert downloaded_image.as_posix() in header_content
    assert (
        rf"\includegraphics[width=0.45\textwidth]{{{downloaded_image.as_posix()}}}\\"
        in header_content
    )
    assert header_content.index(r"\includegraphics") < header_content.index(r"\@title")


def test_title_page_image_local_file_is_included(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "chapter.md").write_text("# Chapter 1\n\nHello world.\n", encoding="utf-8")

    merged_md_dir = tmp_path / "merged"
    merged_md_dir.mkdir()
    out_pdf = tmp_path / "book.pdf"
    image_path = Path(__file__).with_name("pexels-joshuaworoniecki-31891237.jpg")
    captured = {}

    def fake_spinner(cmd, out_pdf_arg, source_spans):
        captured["cmd"] = cmd
        captured["out_pdf"] = out_pdf_arg
        captured["source_spans"] = source_spans

    monkeypatch.setattr(mdfusion, "run_pandoc_with_spinner", fake_spinner)
    monkeypatch.setattr(mdfusion.pypandoc, "get_pandoc_path", lambda: "pandoc")

    params = mdfusion.RunParams(
        root_dir=docs,
        output=str(out_pdf),
        merged_md=merged_md_dir,
        title_page=True,
        title="My Book",
        author="Jane Doe",
        title_page_image=str(image_path),
    )
    mdfusion.run(params)

    cmd = captured["cmd"]
    header_arg = next(arg for arg in cmd if arg.startswith("--include-in-header="))
    header_path = Path(header_arg.split("=", 1)[1])
    header_content = header_path.read_text(encoding="utf-8")

    assert image_path.resolve().as_posix() in header_content
    assert (
        rf"\includegraphics[width=0.45\textwidth]{{{image_path.resolve().as_posix()}}}\\"
        in header_content
    )
    assert header_content.index(r"\includegraphics") < header_content.index(r"\@title")
