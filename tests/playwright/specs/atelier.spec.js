const {test, expect} = require("../fixtures");

// Read-only UI tests. Never connect a printer, send G-code, start a job or flash a disk.
for (const width of [320, 360, 390, 430, 768, 1024, 1366]) {
    test(`Atelier layout and navigation at ${width}px`, async ({
        page,
        loginApi,
        ui
    }, testInfo) => {
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
            await expect(page.getByTestId(`atelier-nav-${section}`)).toHaveAttribute(
                "aria-current",
                "page"
            );
            expect(
                await page.evaluate(
                    () => document.documentElement.scrollWidth <= innerWidth + 1
                )
            ).toBeTruthy();
        }
        if (width <= 759) {
            const navbar = page.locator("#navbar");
            const navSize = await navbar.boundingBox();
            expect(navSize).not.toBeNull();
            expect(navSize.height).toBeLessThanOrEqual(80);
            expect(navSize.x).toBeGreaterThanOrEqual(-1);
            expect(navSize.x + navSize.width).toBeLessThanOrEqual(width + 1);

            await page.getByTestId("atelier-nav-control").click();
            const overflow = await page.evaluate(() => {
                const ids = [
                    "#webcam_plugins_container",
                    "#control-jog-xy",
                    "#control-jog-z",
                    "#control-jog-extrusion",
                    "#control-jog-general",
                    "#jog_distance"
                ];
                return ids
                    .map((id) => document.querySelector(id))
                    .filter(
                        (el) =>
                            el &&
                            el.getClientRects().length &&
                            getComputedStyle(el).visibility !== "hidden"
                    )
                    .filter((el) => {
                        const box = el.getBoundingClientRect();
                        return box.left < -1 || box.right > innerWidth + 1;
                    })
                    .map((el) => el.id);
            });
            expect(overflow).toEqual([]);

            // Native account menu previously rendered outside the left edge
            // on iPhone. Test the actual popup, not only scrollWidth.
            await page.locator("#navbar_login > a").click();
            const accountMenu = page.locator("#login_dropdown_loggedin");
            await expect(accountMenu).toBeVisible();
            const menu = await accountMenu.boundingBox();
            expect(menu).not.toBeNull();
            expect(menu.x).toBeGreaterThanOrEqual(0);
            expect(menu.x + menu.width).toBeLessThanOrEqual(width + 1);
            await page.locator("#navbar_login > a").click();
        }
        await page.getByTestId("atelier-nav-files").click();
        await expect(page.locator("#atelier-files-slot #files_wrapper")).toBeVisible();
        await page.getByTestId("atelier-nav-home").click();
        await page.getByTestId("atelier-connection").click();
        await expect(page.locator("#connection_wrapper")).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(page.locator("body")).not.toHaveClass(/atelier-connection-open/);
        await page.screenshot({
            path: testInfo.outputPath(`atelier-${width}.png`),
            fullPage: true
        });
        expect(errors).toEqual([]);
    });
}

test("Classic fallback preserves the original files widget and tabs", async ({
    page,
    loginApi,
    ui
}) => {
    await loginApi.loginDefault();
    await page.goto("/?classic=1&l10n=en");
    await ui.coreHasLoaded();
    await expect(page.locator("body")).toHaveClass(/atelier-classic/);
    await expect(page.locator("body")).not.toHaveClass(/atelier-ui/);
    await expect(page.locator("#atelier-navigation")).toBeHidden();
    await expect(page.locator("#sidebar #files_wrapper")).toBeVisible();
    await expect(page.locator("#tabs")).toBeVisible();
});

test("Versioned API v2 contracts for connection and file storage", async ({
    page,
    loginApi,
    ui
}) => {
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
    expect(
        await page.evaluate(() => OctoPrint.options.apiVersion.startsWith("2."))
    ).toBeTruthy();
});


/*
 * Device-shaped regression recipes. The Redmi Pad 10.61 has a native
 * 1200x2000 display; 800x1333 CSS px at 1.5x is a representative Android
 * browser scaling preset, not a promise about the user's display-size setting.
 * Safari and the physical tablet still need a final device check.
 */
const fieldDevices = [
    {
        name: "iPhone 17 portrait",
        viewport: {width: 402, height: 874},
        deviceScaleFactor: 3
    },
    {
        name: "iPhone 17 landscape",
        viewport: {width: 874, height: 402},
        deviceScaleFactor: 3
    },
    {
        name: "Redmi Pad 10.61 portrait",
        viewport: {width: 800, height: 1333},
        deviceScaleFactor: 1.5
    },
    {
        name: "Redmi Pad 10.61 landscape",
        viewport: {width: 1333, height: 800},
        deviceScaleFactor: 1.5
    }
];

for (const device of fieldDevices) {
    test.describe(device.name, () => {
        test.use({
            viewport: device.viewport,
            deviceScaleFactor: device.deviceScaleFactor,
            isMobile: true,
            hasTouch: true
        });

        test("navigation, native controls and menus fit the visual viewport", async ({
            page,
            loginApi,
            ui
        }, testInfo) => {
            await loginApi.loginDefault();
            await page.goto("/?l10n=fr");
            await ui.coreHasLoaded();
            await expect(page.locator("body")).toHaveClass(/atelier-ui/);

            const assertFit = async () => {
                const metrics = await page.evaluate(() => {
                    const width = document.documentElement.clientWidth;
                    const viewport = window.innerWidth;
                    const controls = [
                        "#navbar",
                        "#control",
                        "#webcam_plugins_container",
                        "#control-jog-xy",
                        "#control-jog-z",
                        "#control-jog-extrusion",
                        "#control-jog-general"
                    ];
                    const outliers = controls
                        .map((selector) => document.querySelector(selector))
                        .filter((node) => node && node.getClientRects().length)
                        .map((node) => ({
                            id: node.id,
                            left: node.getBoundingClientRect().left,
                            right: node.getBoundingClientRect().right
                        }))
                        .filter((rect) => rect.left < -1 || rect.right > viewport + 1);
                    return {
                        viewport,
                        width,
                        scrollWidth: document.documentElement.scrollWidth,
                        outliers
                    };
                });
                expect(metrics.viewport).toBe(device.viewport.width);
                expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.viewport + 1);
                expect(metrics.outliers).toEqual([]);
            };

            await assertFit();
            await page.getByTestId("atelier-nav-control").click();
            await expect(page.locator("#control")).toBeVisible();
            await assertFit();

            await page.locator("#navbar_login > a").click();
            const loginMenu = page.locator("#login_dropdown_loggedin");
            await expect(loginMenu).toBeVisible();
            const bounds = await loginMenu.boundingBox();
            expect(bounds).not.toBeNull();
            expect(bounds.x).toBeGreaterThanOrEqual(-1);
            expect(bounds.x + bounds.width).toBeLessThanOrEqual(device.viewport.width + 1);
            await page.locator("#navbar_login > a").click();

            await page.getByTestId("atelier-nav-home").click();
            await assertFit();
            await page.screenshot({
                path: testInfo.outputPath(
                    device.name.toLowerCase().replace(/[^a-z0-9]+/g, "-") + ".png"
                ),
                fullPage: true
            });
        });
    });
}
