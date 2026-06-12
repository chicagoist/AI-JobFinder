from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p1:
        print("P1 started")
        with sync_playwright() as p2:
            print("P2 started")
        print("P2 ended")
    print("P1 ended")

test()