"""Browser tests for ARIA using Playwright."""
import time
from playwright.sync_api import sync_playwright

def test_aria():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Collect console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        
        print("TEST 1: Open ARIA homepage")
        page.goto("http://localhost:5173/")
        time.sleep(3)
        
        # Take screenshot of initial state
        page.screenshot(path="C:\\Users\\Go\\Desktop\\ARIA\\test_screenshot_1.png")
        print("  Screenshot saved: test_screenshot_1.png")
        
        print("\nTEST 2: Create account")
        try:
            # Click Create Account
            create_account_btn = page.locator("button:has-text('Create Account')").first
            if create_account_btn.is_visible():
                create_account_btn.click()
                time.sleep(2)
                print("  Clicked Create Account")
            
            # Fill registration form
            email_input = page.locator("input[type='email'], input[placeholder*='email'], input[placeholder*='Email']").first
            if email_input.is_visible():
                email_input.fill("test@test.com")
                print("  Filled email")
            
            password_input = page.locator("input[type='password']").first
            if password_input.is_visible():
                password_input.fill("password123")
                print("  Filled password")
            
            # Find confirm password
            confirm_password_input = page.locator("input[type='password']").nth(1)
            if confirm_password_input.is_visible():
                confirm_password_input.fill("password123")
                print("  Filled confirm password")
            
            # Click Create Account button
            submit_btn = page.locator("button:has-text('Create Account')").first
            if submit_btn.is_visible():
                submit_btn.click()
                time.sleep(3)
                print("  Submitted registration")
            
            page.screenshot(path="C:\\Users\\Go\\Desktop\\ARIA\\test_screenshot_2.png")
            print("  Screenshot saved: test_screenshot_2.png")
            
        except Exception as e:
            print(f"  Registration error: {e}")
        
        print("\nTEST 3: Check if we're past registration")
        try:
            content = page.inner_text("body")
            safe_content = content.encode('ascii', errors='replace').decode('ascii')
            print(f"  Page content (first 500 chars):")
            print(f"  {safe_content[:500]}")
        except Exception as e:
            print(f"  Error: {e}")
        
        print("\nTEST 4: Try to log in")
        try:
            # Find email input
            email_input = page.locator("input[type='email'], input[placeholder*='email'], input[placeholder*='Email']").first
            if email_input.is_visible():
                email_input.fill("test@test.com")
                print("  Filled email")
            
            # Find password input
            password_input = page.locator("input[type='password']").first
            if password_input.is_visible():
                password_input.fill("password123")
                print("  Filled password")
            
            # Click Sign In
            sign_in_btn = page.locator("button:has-text('Sign In')").first
            if sign_in_btn.is_visible():
                sign_in_btn.click()
                time.sleep(3)
                print("  Clicked Sign In")
            
            page.screenshot(path="C:\\Users\\Go\\Desktop\\ARIA\\test_screenshot_3.png")
            print("  Screenshot saved: test_screenshot_3.png")
            
        except Exception as e:
            print(f"  Login error: {e}")
        
        print("\nTEST 5: Check if we're past login")
        try:
            content = page.inner_text("body")
            safe_content = content.encode('ascii', errors='replace').decode('ascii')
            print(f"  Page content (first 500 chars):")
            print(f"  {safe_content[:500]}")
        except Exception as e:
            print(f"  Error: {e}")
        
        print("\nTEST 6: Look for LLM selection")
        try:
            # Look for Local/Ollama selection
            local_btn = page.locator("button:has-text('Local')").first
            if local_btn.is_visible():
                local_btn.click()
                time.sleep(2)
                print("  Selected Local LLM")
            
            page.screenshot(path="C:\\Users\\Go\\Desktop\\ARIA\\test_screenshot_4.png")
            print("  Screenshot saved: test_screenshot_4.png")
        except Exception as e:
            print(f"  Error: {e}")
        
        print("\nTEST 7: Check current state")
        try:
            content = page.inner_text("body")
            safe_content = content.encode('ascii', errors='replace').decode('ascii')
            print(f"  Page content (first 500 chars):")
            print(f"  {safe_content[:500]}")
        except Exception as e:
            print(f"  Error: {e}")
        
        print("\nTEST 8: Try to navigate to Analysis")
        try:
            # Look for Analysis in sidebar
            analysis_elements = page.locator("text=Analysis").all()
            print(f"  Found {len(analysis_elements)} Analysis elements")
            
            for elem in analysis_elements:
                try:
                    if elem.is_visible():
                        print(f"  Clicking visible Analysis element")
                        elem.click()
                        time.sleep(2)
                        page.screenshot(path="C:\\Users\\Go\\Desktop\\ARIA\\test_screenshot_5.png")
                        print("  Screenshot saved: test_screenshot_5.png")
                        break
                except:
                    pass
        except Exception as e:
            print(f"  Error: {e}")
        
        print("\nTEST 9: Try to navigate to Insights")
        try:
            insights_elements = page.locator("text=Insights").all()
            print(f"  Found {len(insights_elements)} Insights elements")
            
            for elem in insights_elements:
                try:
                    if elem.is_visible():
                        print(f"  Clicking visible Insights element")
                        elem.click()
                        time.sleep(2)
                        page.screenshot(path="C:\\Users\\Go\\Desktop\\ARIA\\test_screenshot_6.png")
                        print("  Screenshot saved: test_screenshot_6.png")
                        break
                except:
                    pass
        except Exception as e:
            print(f"  Error: {e}")
        
        print("\nTEST 10: Check for console errors")
        if console_errors:
            print(f"  Found {len(console_errors)} console errors:")
            for err in console_errors[:10]:
                safe_err = err[:150].encode('ascii', errors='replace').decode('ascii')
                print(f"    - {safe_err}")
        else:
            print("  No console errors found")
        
        browser.close()
        print("\nAll tests completed!")

if __name__ == "__main__":
    test_aria()
