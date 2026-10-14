const {test, expect} = require("../fixtures");

// Read-only UI tests. Never connect a printer, send G-code, start a job or flash a disk.
for (const width of [360, 390, 768, 1024, 1366]) {
    test(`Atelier layout and navigation at ${width}px`, async ({page, loginApi, ui}, testInfo) => {
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.setViewportSize({width, height: 900});
        await loginApi.loginDefault();
        await page.goto("/?l10n=fr");
        await ui.coreHasLoaded();
        await expect(page.locator("body")).toHaveClass(/atelier-ui/);
        await expect(page.locator(".atelier-job")).toBeVisible();
        await expect(page.getByTestId("atelier-print")).toBeDisabled();
        for (const section of ["files", "control", "camera", "home"]) {
            await page.getByTestId(`atelier-nav-${section}`).click();
            await expect(page.getByTestId(`atelier-nav-${section}`)).toHaveAttribute("aria-current", "page");
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
        }
        await page.getByTestId("atelier-nav-files").click();
        await expect(page.locator("#atelier-files-slot #files_wrapper")).toBeVisible();
        await page.getByTestId("atelier-nav-home").click();
        await page.getByTestId("atelier-connection").click();
        await expect(page.locator("#connection_wrapper")).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(page.locator("body")).not.toHaveClass(/atelier-connection-open/);
        await page.screenshot({path: testInfo.outputPath(`atelier-${width}.png`), fullPage: true});
        expect(errors).toEqual([]);
    });
}

test("Classic fallback preserves the original files widget and tabs", async ({page, loginApi, ui}) => {
    await loginApi.loginDefault();
    await page.goto("/?classic=1&l10n=en");
    await ui.coreHasLoaded();
    await expect(page.locator("body")).toHaveClass(/atelier-classic/);
    await expect(page.locator("body")).not.toHaveClass(/atelier-ui/);
    await expect(page.locator("#atelier-navigation")).toBeHidden();
    await expect(page.locator("#sidebar #files_wrapper")).toBeVisible();
    await expect(page.locator("#tabs")).toBeVisible();
});
