async page => {
  const recordingPath = 'evidence/audio-learning-chain/learning-loop.webm';
  const screenshotPath = 'evidence/audio-learning-chain/learning-loop-desktop.png';
  const mobileScreenshotPath = 'evidence/audio-learning-chain/learning-loop-mobile.png';
  const url = 'http://127.0.0.1:8765/evidence/audio-learning-chain/';

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screencast.start({
    path: recordingPath,
    size: { width: 1280, height: 800 },
  });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => window.__evidenceReady === true);

  await page.screencast.showOverlay(`
    <div style="position:absolute;left:24px;bottom:24px;padding:10px 14px;border-left:4px solid #c26a2d;background:#18201f;color:#fff;font:600 13px 'Microsoft YaHei',sans-serif;">
      01 学习规则：整数毫秒，左闭右开，精确贴合锚点
    </div>
  `, { duration: 1800 });
  await page.waitForTimeout(500);

  await page.getByTestId('submit-attempt').click();
  await page.locator('#feedback-panel[data-state="failed"]').waitFor();
  await page.screencast.showOverlay(`
    <div style="position:absolute;right:24px;bottom:24px;padding:10px 14px;border-left:4px solid #a23d32;background:#fbfaf5;color:#18201f;font:600 13px 'Microsoft YaHei',sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.18);">
      02 错误尝试：boundary_alignment_mismatch
    </div>
  `, { duration: 1800 });
  await page.waitForTimeout(500);

  await page.getByTestId('open-remediation').click();
  await page.locator('#remediation-panel:not([hidden])').waitFor();
  await page.screencast.showOverlay(`
    <div style="position:absolute;right:24px;bottom:24px;padding:10px 14px;border-left:4px solid #c26a2d;background:#fbfaf5;color:#18201f;font:600 13px 'Microsoft YaHei',sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.18);">
      03 规则反馈已链接到能力与补强资源
    </div>
  `, { duration: 1800 });
  await page.waitForTimeout(500);

  await page.getByTestId('apply-remediation').click();
  await page.waitForTimeout(900);
  await page.getByTestId('retry-attempt').click();
  await page.locator('#feedback-panel[data-state="passed"]').waitFor();
  await page.screencast.showOverlay(`
    <div style="position:absolute;right:24px;bottom:24px;padding:10px 14px;border-left:4px solid #23654b;background:#18201f;color:#fff;font:600 13px 'Microsoft YaHei',sans-serif;">
      04 成功重试：score 1.0
    </div>
  `, { duration: 1800 });
  await page.waitForTimeout(700);

  await page.screenshot({ path: screenshotPath, fullPage: false });
  await page.screencast.stop();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  const mobileLayout = await page.evaluate(() => {
    const viewportWidth = window.innerWidth;
    const outsideViewport = [...document.querySelectorAll('body *')]
      .filter((element) => {
        const style = getComputedStyle(element);
        const bounds = element.getBoundingClientRect();
        return style.display !== 'none' && bounds.width > 0 &&
          (bounds.left < -0.5 || bounds.right > viewportWidth + 0.5);
      })
      .map((element) => element.id || element.className || element.tagName);
    const orderedSelectors = [
      '.masthead',
      '.lesson-rail',
      '.rule-band',
      '.timeline-section',
      '.feedback-section',
    ];
    const orderedBounds = orderedSelectors.map((selector) =>
      document.querySelector(selector).getBoundingClientRect(),
    );
    const overlappingSections = orderedBounds.slice(1).some(
      (bounds, index) => bounds.top < orderedBounds[index].bottom - 0.5,
    );
    return {
      horizontalOverflow: document.documentElement.scrollWidth > viewportWidth,
      outsideViewport,
      overlappingSections,
      viewport: { width: window.innerWidth, height: window.innerHeight },
    };
  });
  if (
    mobileLayout.horizontalOverflow ||
    mobileLayout.outsideViewport.length ||
    mobileLayout.overlappingSections
  ) {
    throw new Error(`Mobile layout validation failed: ${JSON.stringify(mobileLayout)}`);
  }
  await page.locator('#feedback-panel').scrollIntoViewIfNeeded();
  await page.screenshot({ path: mobileScreenshotPath, fullPage: false });
  return mobileLayout;
}
