import pytest

from tigeri.agents.invoice.adapters.s3 import S3DocumentRef, _is_directory_bucket


def test_parse_s3_uri():
    ref = S3DocumentRef.parse("s3://my-bucket/invoices/abc.pdf")
    assert ref.bucket == "my-bucket"
    assert ref.key == "invoices/abc.pdf"


def test_parse_s3_colon_form():
    ref = S3DocumentRef.parse("s3:my-bucket:invoices/abc.pdf")
    assert ref.bucket == "my-bucket"
    assert ref.key == "invoices/abc.pdf"


def test_parse_rejects_unknown_scheme():
    with pytest.raises(ValueError):
        S3DocumentRef.parse("file:///tmp/x.pdf")


def test_directory_bucket_detection():
    assert _is_directory_bucket("trigeri--global--use1-az4--x-s3")
    assert not _is_directory_bucket("my-standard-bucket")
