"""Small Playwright smoke test for the local GeneScope UI; not a research analysis."""
from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


ARTIFACTS = Path(__file__).resolve().parent / ".smoke"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BASE_URL = os.environ.get("GENESCOPE_SMOKE_BASE", "http://127.0.0.1:5173")
PAGES = [
    ("RNA-Seq 数据探索", "RNA-Seq 数据探索"),
    ("特征选择与稳定性", "特征选择与稳定性"),
    ("模型性能对比", "模型性能对比"),
    ("特征融合与消融", "特征融合与消融"),
    ("单样本预测", "单样本预测"),
    ("关于项目", "关于项目"),
    ("交互式模型实验室", "交互式模型实验室"),
]


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page_errors: list[str] = []
    request_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: request_errors.append(f"{request.method} {request.url}: {request.failure}"))

        page.goto(BASE_URL + "/", wait_until="networkidle", timeout=60000)
        hero_heading = page.locator(".hero-copy h1")
        hero_heading.wait_for(timeout=15000)
        if "基于 RNA-Seq" not in (hero_heading.text_content() or ""):
            raise AssertionError("首页标题没有正确渲染")
        page.get_by_text("801", exact=True).first.wait_for(timeout=10000)
        menu_background = page.locator(".desktop-sidebar .side-menu .arco-menu-item").nth(1).evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        if menu_background == "rgb(255, 255, 255)":
            raise AssertionError("侧栏非选中导航项仍使用白色背景，文字对比度不足")

        performance = page.request.get(BASE_URL + "/api/v1/features/performance?method=anova")
        stability = page.request.get(BASE_URL + "/api/v1/features/stability?method=anova&k=50")
        if performance.status != 200 or stability.status != 200:
            raise AssertionError("真实特征性能或稳定性 API 请求失败")
        performance_rows = performance.json()["data"]["records"]
        stability_rows = stability.json()["data"]["records"]
        if len(performance_rows) != 6 or not any(row.get("validation_macro_f1_mean") is not None for row in performance_rows):
            raise AssertionError("性能曲线 API 没有返回六个K值的真实指标")
        if len(stability_rows) != 1 or stability_rows[0].get("jaccard_mean") is None:
            raise AssertionError("稳定性图 API 没有返回真实 Jaccard 指标")
        page.screenshot(path=str(ARTIFACTS / "dashboard.png"), full_page=True)
        visited = ["研究总览"]

        for label, heading in PAGES:
            page.get_by_text(label, exact=True).first.click()
            page.wait_for_load_state("networkidle", timeout=60000)
            page.get_by_role("heading", name=heading, exact=True).wait_for(timeout=15000)
            visited.append(label)
            if label == "特征选择与稳定性":
                page.locator(".panel-card canvas").first.wait_for(timeout=15000)
                chart_pixels = page.locator(".panel-card .echarts-for-react").evaluate_all("""wrappers => wrappers.slice(0, 2).map(wrapper => {
                    const canvases = Array.from(wrapper.querySelectorAll('canvas'));
                    let blue = 0, teal = 0, amber = 0;
                    for (const canvas of canvases) {
                        const context = canvas.getContext('2d');
                        const image = context.getImageData(0, 0, canvas.width, canvas.height).data;
                        for (let i = 0; i < image.length; i += 4) {
                            const [r, g, b, a] = image.slice(i, i + 4);
                            if (a < 160) continue;
                            if (b > r * 1.25 && b > g * 1.05 && r < 120) blue++;
                            if (g > r * 1.25 && g > b * 1.05 && r < 120) teal++;
                            if (r > g * 1.25 && g > b * 1.15 && r < 240) amber++;
                        }
                    }
                    return { canvasCount: canvases.length, widths: canvases.map(canvas => canvas.width), heights: canvases.map(canvas => canvas.height), blue, teal, amber };
                })""")
                if len(chart_pixels) < 2 or chart_pixels[0]["blue"] < 200 or chart_pixels[0]["teal"] < 200:
                    raise AssertionError(f"性能曲线未绘制真实指标线：{chart_pixels}")
                if chart_pixels[1]["teal"] < 500 or chart_pixels[1]["amber"] < 500:
                    raise AssertionError(f"稳定性图未绘制真实 Jaccard/Kuncheva 柱：{chart_pixels}")
                page.screenshot(path=str(ARTIFACTS / "features.png"), full_page=True)
            if label == "单样本预测":
                health = page.request.get(BASE_URL + "/api/v1/health").json()
                expected = "模型可用" if health["data"]["model_available"] else "模型环境不可用"
                page.get_by_text(expected, exact=True).wait_for(timeout=15000)

        page.locator(".theme-control .arco-switch").click()
        dark_theme = page.evaluate("document.documentElement.classList.contains('arco-theme-dark')")
        if not dark_theme:
            raise AssertionError("深色主题切换没有应用到根元素")

        if page_errors:
            raise AssertionError(f"浏览器运行时错误：{page_errors}")
        if request_errors:
            raise AssertionError(f"浏览器请求失败：{request_errors}")

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        mobile.goto(BASE_URL + "/", wait_until="networkidle", timeout=60000)
        if mobile.locator(".desktop-sidebar").is_visible():
            raise AssertionError("窄屏下桌面侧栏没有隐藏")
        mobile.get_by_role("button", name="打开导航").click()
        mobile.locator(".nav-drawer").wait_for(state="visible", timeout=5000)
        mobile.locator(".nav-drawer").get_by_text("RNA-Seq 数据探索", exact=True).click()
        mobile.get_by_role("heading", name="RNA-Seq 数据探索", exact=True).wait_for(timeout=10000)
        mobile.close()

        print(json.dumps({"visited_pages": visited, "dark_theme": dark_theme,
                          "page_errors": page_errors, "request_errors": request_errors,
                          "chart_pixels": chart_pixels,
                          "performance_values": [row.get("validation_macro_f1_mean") for row in performance_rows],
                          "stability_values": [stability_rows[0].get("jaccard_mean"), stability_rows[0].get("kuncheva_mean")],
                          "screenshots": [str(ARTIFACTS / "dashboard.png"), str(ARTIFACTS / "features.png")]},
                         ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
