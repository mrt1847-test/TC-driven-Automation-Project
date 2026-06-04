import pytest
from playwright.sync_api import Page, expect

from flows.sample_case_001_flow import SampleCase001Flow
from pages.generated_page import SAMPLE_PAGE_URL


@pytest.fixture
def flow(page: Page):
    return SampleCase001Flow(page)


def test_sample_case_001(page: Page):
    f = SampleCase001Flow(page)
    f.execute()
    expect(page).to_have_url(SAMPLE_PAGE_URL)
