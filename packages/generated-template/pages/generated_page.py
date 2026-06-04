from pages.base_page import BasePage

SAMPLE_PAGE_URL = "data:text/html,%3Ca%20href%3D%22%23done%22%3EMore%20information%3C%2Fa%3E"


class GeneratedPage(BasePage):
    def open_home(self):
        self.page.goto(SAMPLE_PAGE_URL)

    def click_more_information(self):
        self.page.get_by_role("link", name="More information").click()
