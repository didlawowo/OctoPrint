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

test("Versioned API v2 contracts for connection and file storage", async ({page, loginApi, ui}) => {
    await loginApi.loginDefault();
    await page.goto("/?l10n=fr");
    await ui.coreHasLoaded();

    const headers = {"X-OctoPrint-Api-Version": "2.0.0"};
    const connection = await page.request.get("/api/connection", {headers});
    expect(connection.ok()).toBeTruthy();
    const connectionData = await connection.json();
    expect(Array.isArray(connectionData.options.connectors)).toBeTruthy();
    expect(connectionData.current).toHaveProperty("state");
    expect(connectionData.options).toHaveProperty("preferredConnector");
    if (connectionData.options.preferredConnector != null) {
        expect(typeof connectionData.options.preferredConnector.connector).toBe("string");
    }

    const files = await page.request.get("/api/files?recursive=true", {headers});
    expect(files.ok()).toBeTruthy();
    const storageData = await files.json();
    for (const storage of Object.values(storageData)) {
        expect(Array.isArray(storage.files)).toBeTruthy();
    }

    // A version mismatch would select OctoPrint's pre-2.0 schemas instead.
    expect(await page.evaluate(() => OctoPrint.options.apiVersion.startsWith("2."))).toBeTruthy();
});
