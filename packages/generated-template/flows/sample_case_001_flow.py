from pages.generated_page import GeneratedPage


class SampleCase001Flow:
    def __init__(self, page):
        self.page = page
        self.generated_page = GeneratedPage(page)

    def execute(self):
        self.generated_page.open_home()
        self.generated_page.click_more_information()
