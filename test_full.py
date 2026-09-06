import asyncio
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        # Login
        await page.goto("http://localhost:5173", timeout=30000)
        await asyncio.sleep(2)
        await page.locator('input[type="email"]').first.fill("test@test.com")
        await page.locator('input[type="password"]').first.fill("password123")
        await page.locator('button:has-text("Sign In")').first.click()
        await asyncio.sleep(3)

        # Select Cloud LLM
        llm = page.locator('button:has-text("Use Cloud LLM")')
        if await llm.count() > 0:
            await llm.first.click()
            await asyncio.sleep(3)

        # Wait for dashboard + auto-connect
        for i in range(20):
            await asyncio.sleep(1)
            body = await page.locator("body").inner_text()
            if "ARIA Intelligence" in body:
                print(f"Dashboard ready after {i+1}s")
                break
        await asyncio.sleep(2)

        # ===== TEST 1: Dashboard autocomplete =====
        print("\n=== TEST 1: Dashboard autocomplete ===")
        sugg = page.locator('.ai-suggestion-item')
        count = await sugg.count()
        print(f"  Suggestions: {count} {'PASS' if count > 0 else 'FAIL'}")

        # ===== TEST 2: Dashboard question submission =====
        print("\n=== TEST 2: Dashboard question submission ===")
        ai_input = page.locator('.ai-panel-input, input[placeholder*="Ask"]')
        await ai_input.first.fill("How many customers are there?")
        await asyncio.sleep(1)
        await page.locator('.ai-panel-submit').first.click()

        for i in range(30):
            await asyncio.sleep(1)
            body = await page.locator("body").inner_text()
            if "Analysis complete" in body or "ANALYSIS" in body:
                print(f"  Analysis completed in {i+1}s PASS")
                break
        else:
            print("  Analysis did NOT complete in 30s FAIL")

        # Check result elements
        body = await page.locator("body").inner_text()
        has_back = "Back" in body
        has_result = "TOTAL CUSTOMER COUNT" in body or "EXECUTIVE SUMMARY" in body
        print(f"  Back button: {'PASS' if has_back else 'FAIL'}")
        print(f"  Result content: {'PASS' if has_result else 'FAIL'}")

        # ===== TEST 3: Insights page =====
        print("\n=== TEST 3: Insights page ===")
        await page.locator('text=Insights').first.click()
        await asyncio.sleep(2)
        body = await page.locator("body").inner_text()
        has_back_insights = "Back" in body
        has_question = "How many customers" in body
        has_insight_content = "Analysis complete" in body or "insight" in body.lower()
        has_insights_page = "INTELLIGENCE WORKSPACE" in body
        print(f"  Page loads: {'PASS' if has_insights_page else 'FAIL'}")
        print(f"  Back button: {'PASS' if has_back_insights else 'FAIL'}")
        print(f"  Shows submitted question: {'PASS' if has_question else 'FAIL'}")
        print(f"  Has insight content: {'PASS' if has_insight_content else 'FAIL'}")

        # ===== TEST 4: Analysis page =====
        print("\n=== TEST 4: Analysis page ===")
        await page.locator('text=Analysis').first.click()
        await asyncio.sleep(2)
        body = await page.locator("body").inner_text()
        has_back_analysis = "Back" in body
        has_question_analysis = "How many customers" in body
        has_analysis_page = "ACTIVE ANALYTICAL WORKSPACE" in body or "Analytical" in body
        has_chart = "CustomerCount" in body or "Evidence" in body
        has_table = "Processed data" in body
        print(f"  Page loads: {'PASS' if has_analysis_page else 'FAIL'}")
        print(f"  Back button: {'PASS' if has_back_analysis else 'FAIL'}")
        print(f"  Shows submitted question: {'PASS' if has_question_analysis else 'FAIL'}")
        print(f"  Has chart/data: {'PASS' if has_chart else 'FAIL'}")
        print(f"  Has data table: {'PASS' if has_table else 'FAIL'}")

        # ===== TEST 5: All other pages load =====
        print("\n=== TEST 5: Other pages regression ===")
        for page_name in ["Dashboard", "Predictions", "Prescriptions", "Hypothesis", "Reports", "Settings", "Schema"]:
            try:
                link = page.locator(f'text={page_name}').first
                await link.click()
                await asyncio.sleep(2)
                body = await page.locator("body").inner_text()
                loaded = page_name.upper() in body or page_name in body
                print(f"  {page_name}: {'PASS' if loaded else 'FAIL'}")
            except Exception as e:
                print(f"  {page_name}: ERROR - {str(e)[:80]}")

        # ===== ERRORS =====
        if errors:
            print(f"\n=== Page Errors ({len(errors)}) ===")
            for e in errors[:5]:
                print(f"  {e[:150]}")
        else:
            print("\n=== No page errors ===")

        await browser.close()
        print("\nAll tests complete!")

asyncio.run(test())
