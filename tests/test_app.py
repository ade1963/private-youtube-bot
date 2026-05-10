import argparse

import pytest

from app import audio_quality, build_options, build_parser, build_video_format


def test_audio_defaults_to_mp3_download(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["https://example.com/video", "--output-dir", str(tmp_path)])

    options = build_options(args)

    assert options["format"] == "bestaudio/best"
    assert options["noplaylist"] is True
    assert options["outtmpl"].startswith(str(tmp_path))
    assert options["postprocessors"] == [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }
    ]


def test_video_uses_resolution_cap(tmp_path):
    parser = build_parser()
    args = parser.parse_args(
        [
            "https://example.com/video",
            "--media",
            "video",
            "--resolution",
            "1080",
            "--output-dir",
            str(tmp_path),
        ]
    )

    options = build_options(args)

    assert "height<=1080" in options["format"]
    assert options["merge_output_format"] == "mp4"
    assert "postprocessors" not in options


def test_playlist_is_disabled_unless_requested(tmp_path):
    parser = build_parser()
    args = parser.parse_args(
        ["https://example.com/playlist", "--playlist", "--output-dir", str(tmp_path)]
    )

    options = build_options(args)

    assert options["noplaylist"] is False


@pytest.mark.parametrize("quality", ["0", "5", "10", "128", "192", "320"])
def test_audio_quality_accepts_valid_values(quality):
    assert audio_quality(quality) == quality


@pytest.mark.parametrize("quality", ["", "-1", "11", "abc"])
def test_audio_quality_rejects_invalid_values(quality):
    with pytest.raises(argparse.ArgumentTypeError):
        audio_quality(quality)


def test_video_format_falls_back_to_best_available():
    assert build_video_format(720).endswith("bv*+ba/b")
