import scrapy
from datetime import date, timedelta

MIN_DATE = date(1952,11,14) #UK Weekly Singles Charts began in 1952, and TCTM does not record singles charts after the 20th century.
MAX_DATE = date(1999,12,26)
class ChartsSpider(scrapy.Spider):
    name = "charts"

    def get_date(self): #Argument validation
        options = ["year", "decade", "week"] #Mutually exclusive arguments
        selected_option = [arg for arg in options if hasattr(self, arg)]
        if hasattr(self, "from_date") != hasattr(self, "to_date"):
            raise ValueError("Expected both arguments: -a from_date=YYYY-MM-DD, -a to_date=YYYY-MM-DD")
        if hasattr(self, "from_date"):
            selected_option.append("range")
        if len(selected_option) > 1:
            raise ValueError("Expected one search option: -a year=YYYY | -a decade=YYYY | -a week=YYYY-MM-DD | -a from_date=YYYY-MM-DD, -a to_date=YYYY-MM-DD")

        if "year" in selected_option:
            year = int(self.year)
            from_date = date(year,1,1)
            to_date = date(year,12,31)
        elif "decade" in selected_option:
            decade = int(self.decade)
            if decade % 10 != 0:
                raise ValueError("Expected decade to end with 0")
            from_date = date(decade,1,1)
            to_date = date(decade+9,12,31)
        elif "week" in selected_option:
            from_date = date.fromisoformat(self.week)
            to_date = min(from_date + timedelta(days=6), MAX_DATE)
        elif "range" in selected_option:
            from_date = date.fromisoformat(self.from_date)
            to_date = date.fromisoformat(self.to_date)
        else: #Default parameters - set to scrape all existing charts.
            from_date = MIN_DATE
            to_date = MAX_DATE

        if from_date > to_date:
            raise ValueError("from_date cannot be greater than to_date")
        if "year" in selected_option or "decade" in selected_option: #Clamping
            if to_date < MIN_DATE:
                raise ValueError(f"Date cannot be before {MIN_DATE}")
            if from_date > MAX_DATE:
                raise ValueError(f"Date cannot be after {MAX_DATE}")
            from_date = max(from_date, MIN_DATE)
            to_date = min(to_date, MAX_DATE)
        else: #Bounds checking
            if from_date < MIN_DATE:
                raise ValueError(f"Date cannot be before {MIN_DATE}")
            if to_date > MAX_DATE:
                raise ValueError(f"Date cannot be after {MAX_DATE}")
        return from_date, to_date

    def start_requests(self): #Crawler iterates through every specified weekly chart, by partitioning the date range into 7 day-long intervals and adjusting the URL search parameters
        try:
            from_date, to_date = self.get_date()
            self.logger.info(f"Scraping chart data from {from_date} to {to_date}")
        except ValueError as error:
            self.logger.error(f"Invalid argument: {error}")
            return
        
        while from_date <= to_date:
            week_date = min(from_date + timedelta(days=6), to_date)
            url = f"https://www.charttimemachine.com/?format=keyword&date_from={from_date}&date_to={week_date}&pos_high=1&pos_low=100&results=100"
            yield scrapy.Request(url, callback=self.parse)
            from_date += timedelta(days=7)

    def parse(self, response): #Scrapes weekly charts and extracts their available relevant data, parsing the webpage's HTML.
        charts = response.css("table.chart_table tr:has(div.position_display)")
        if not charts:
            self.logger.warning(f"No chart entries found from {response.url}")

        for chart in charts: #CSS selectors
            item = {
                "position": chart.css("td div::text").get(),
                "artist":   chart.css("td:nth-child(2) a::text").get(),
                "song":     chart.css("td:nth-child(3) a::text").get(),
                "label":    chart.css("td:nth-child(4) a::text").get(),
                "week":     chart.css("td:nth-child(5) span.show_mobile::text").get(),
                "url":      response.url, #Data provenance
            }
            song_url = chart.css("td:nth-child(3) a::attr(href)").get()
            
            if song_url:
                yield response.follow(song_url, callback=self.parse_song, cb_kwargs={"item": item}, dont_filter=True)
            else:
                self.logger.warning(f'Song URL not found from {item["song"]}, {item["artist"]}')
                yield item

        pagination = response.css("table.chart_table tr.pagination") #A total of 3 chart weeks contain >100 entries, and therefore require pagination - caused by tied positions?
        current_page = pagination.css("span::text").get()
        if current_page:
            next_page = int(current_page) + 1
            next_url = pagination.css(f'a[href*="Page${next_page}"]')
            if next_url:
                yield scrapy.FormRequest.from_response(
                    response, 
                    formdata={
                        "__EVENTTARGET":   "ctl00$ContentPlaceHolder1$gvArtistCharts",
                        "__EVENTARGUMENT": f"Page${next_page}",
                    },
                    callback=self.parse,
                    dont_click=True,
                    )

    def parse_song(self, response, item): #Scrapes individual song webpages for their genre and style. Webpages can be revisited from Scrapy's cache
        def values(label):
            texts = response.css(f'div.artist_info_left:contains("{label}") + div.artist_info_right::text').getall()
            return "|".join(text.strip() for text in texts if text.strip()) or None
        item["genre"] = values("Genre")
        item["style"] = values("Style") #Note: A number of songs do not list a style
        item["song_url"] = response.url
        yield item