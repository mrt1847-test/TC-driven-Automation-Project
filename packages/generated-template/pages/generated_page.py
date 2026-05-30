from pages.base_page import BasePage


class GeneratedPage(BasePage):
    def open_home(self):
        self.page.goto("https://example.com")

    def click_more_information(self):
        self.page.get_by_role("link", name="More information").click()
