export const JD_PUBLISH_URL = "https://dr.jd.com/n/publish-video.html";

const pause = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

async function fresh(tab) {
  return await tab.playwright.domSnapshot();
}

function assertJob(job) {
  if (!job || typeof job !== "object") {
    throw new Error("缺少发布任务");
  }
  if (!job.video_path) {
    throw new Error("缺少本地视频路径");
  }
  if (!job.cover_path) {
    throw new Error("缺少本地封面路径");
  }
  const titleLength = Array.from(String(job.title || "").trim()).length;
  if (titleLength < 5 || titleLength > 27) {
    throw new Error("标题必须为5-27个字");
  }
  if (!Array.isArray(job.skus) || job.skus.length < 1 || job.skus.length > 10) {
    throw new Error("商品SKU必须为1-10个");
  }
  if (!String(job.topic || "").startsWith("#")) {
    throw new Error("参与话题必须以#开头");
  }
  if (!String(job.label_type || "").trim()) {
    throw new Error("缺少标签类型");
  }
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(job.scheduled_publish_time || "")) {
    throw new Error("定时发布时间格式必须为YYYY-MM-DD HH:mm");
  }
}

async function uploadVideo(tab, videoPath, timeoutMs) {
  await fresh(tab);
  const uploadButton = tab.playwright.getByRole("button", {
    name: "plus 上传视频",
    exact: true,
  });
  if ((await uploadButton.count()) !== 1) {
    throw new Error("没有唯一找到京东上传视频按钮");
  }
  const chooserOutcome = tab.playwright
    .waitForEvent("filechooser", { timeoutMs: 10000 })
    .then(
      (chooser) => ({ chooser, error: null }),
      (error) => ({ chooser: null, error }),
    );
  try {
    await uploadButton.click({ force: true });
    const outcome = await chooserOutcome;
    if (outcome.error || !outcome.chooser) {
      throw outcome.error || new Error("未返回文件选择器");
    }
    await outcome.chooser.setFiles([videoPath]);
  } catch (error) {
    throw new Error(`京东视频文件选择器未能打开：${error.message}`);
  }

  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    await pause(2000);
    const snapshot = await fresh(tab);
    if (!snapshot.includes("等待视频上传")) {
      return snapshot;
    }
    if (/上传失败|转码失败|视频处理失败/.test(snapshot)) {
      throw new Error("京东后台提示视频上传或处理失败");
    }
  }
  throw new Error(`视频上传等待超过${Math.round(timeoutMs / 1000)}秒`);
}

async function fillTitle(tab, title) {
  await fresh(tab);
  const textbox = tab.playwright.getByRole("textbox", {
    name: "添加一个亮眼的标题吧，5~27个字",
  });
  await textbox.fill(title);
}

async function selectCover(tab, coverPath) {
  const snapshot = await fresh(tab);
  if (snapshot.includes('img "封面预览"')) {
    return;
  }
  let input = tab.playwright.locator(
    'input[type="file"][accept="image/*"]',
  );
  if ((await input.count()) === 0) {
    const coverEntries = tab.playwright.getByText("设置封面", {
      exact: true,
    });
    const coverEntryCount = await coverEntries.count();
    if (coverEntryCount !== 2) {
      throw new Error("京东设置封面入口数量异常");
    }
    await coverEntries.nth(1).click({ force: true });
    await fresh(tab);
    await tab.playwright.waitForTimeout(500);
    input = tab.playwright.locator(
      'input[type="file"][accept="image/*"]',
    );
  }
  if ((await input.count()) !== 1) {
    throw new Error("没有唯一找到京东封面文件输入框");
  }
  const chooserOutcome = tab.playwright
    .waitForEvent("filechooser", { timeoutMs: 10000 })
    .then(
      (chooser) => ({ chooser, error: null }),
      (error) => ({ chooser: null, error }),
    );
  await input.click();
  const outcome = await chooserOutcome;
  if (outcome.error || !outcome.chooser) {
    throw new Error("京东封面文件选择器未能打开");
  }
  await outcome.chooser.setFiles([coverPath]);
  let cropSnapshot = "";
  for (let index = 0; index < 20; index += 1) {
    await tab.playwright.waitForTimeout(500);
    cropSnapshot = await fresh(tab);
    if (cropSnapshot.includes("图片小于200kb")) {
      break;
    }
    const candidateDialog = tab.playwright.getByRole("dialog", {
      name: "设置封面",
      exact: true,
    });
    if ((await candidateDialog.count()) === 1) {
      const candidateConfirm = candidateDialog.getByRole("button", {
        name: "确定",
        exact: true,
      });
      if (
        (await candidateConfirm.count()) === 1 &&
        (await candidateConfirm.isEnabled())
      ) {
        break;
      }
    }
  }
  if (cropSnapshot.includes("图片小于200kb")) {
    throw new Error("封面图片必须大于200KB");
  }
  const dialog = tab.playwright.getByRole("dialog", {
    name: "设置封面",
    exact: true,
  });
  if ((await dialog.count()) !== 1) {
    throw new Error("京东封面裁剪窗口未正常打开");
  }
  const confirm = dialog.getByRole("button", {
    name: "确定",
    exact: true,
  });
  if ((await confirm.count()) !== 1 || !(await confirm.isEnabled())) {
    throw new Error("京东封面尚未处理完成");
  }
  await confirm.click();
  let selected = "";
  for (let index = 0; index < 10; index += 1) {
    await tab.playwright.waitForTimeout(300);
    selected = await fresh(tab);
    if (selected.includes('img "封面预览"')) {
      break;
    }
  }
  if (!selected.includes('img "封面预览"')) {
    throw new Error("京东封面设置失败");
  }
}

async function selectProducts(tab, skus) {
  await fresh(tab);
  const counter = tab.playwright.getByText("0/10", { exact: true });
  await counter.locator("xpath=..").click();
  await fresh(tab);
  await tab.playwright.waitForTimeout(500);
  const dialog = tab.playwright.getByRole("dialog");
  const panel = dialog.getByRole("tabpanel", {
    name: "本店商品",
    exact: true,
  });

  for (let index = 0; index < skus.length; index += 1) {
    const sku = skus[index];
    const search = panel.getByRole("textbox", {
      name: "请输入商品名称或skuid搜索本店商品",
      exact: true,
    });
    if ((await search.count()) !== 1) {
      throw new Error("京东SKU搜索框数量异常");
    }
    await search.fill(String(sku));
    await search.press("Enter");
    await pause(600);
    const snapshot = await fresh(tab);
    if (!snapshot.includes(String(sku))) {
      throw new Error(`京东商品选择器没有找到SKU：${sku}`);
    }
    const checkboxes = panel.getByRole("checkbox");
    if ((await checkboxes.count()) !== 1) {
      throw new Error(`SKU ${sku} 搜索结果不唯一或没有可选商品`);
    }
    await checkboxes.click();
    let selected = "";
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await tab.playwright.waitForTimeout(200);
      selected = await fresh(tab);
      if (selected.includes(`已选${index + 1}`)) {
        break;
      }
    }
    if (!selected.includes(`已选${index + 1}`)) {
      throw new Error(`SKU ${sku} 未能加入已选商品`);
    }
  }

  await dialog.getByRole("button", { name: "确定", exact: true }).click();
  await fresh(tab);
}

async function selectTopic(tab, topic) {
  await fresh(tab);
  const topicEntry = tab.playwright
    .getByText("点击添加话题", { exact: true })
    .locator("xpath=..");
  if ((await topicEntry.count()) !== 1) {
    throw new Error("京东话题入口数量异常");
  }
  let dialog = tab.playwright.getByRole("dialog");
  let search = dialog.getByRole("textbox", { name: "输入关键词搜索" });
  for (let attempt = 0; attempt < 3 && (await search.count()) !== 1; attempt += 1) {
    await topicEntry.click({ force: true });
    for (let index = 0; index < 10 && (await search.count()) !== 1; index += 1) {
      await tab.playwright.waitForTimeout(300);
      await fresh(tab);
      dialog = tab.playwright.getByRole("dialog");
      search = dialog.getByRole("textbox", { name: "输入关键词搜索" });
    }
  }
  if ((await search.count()) !== 1) {
    throw new Error("京东话题搜索面板未正常打开");
  }
  const topicName = String(topic).replace(/^#/, "");
  const topicDetail = `#${topicName}详情`;
  await search.fill(topicName);
  await search.press("Enter");
  await pause(900);
  const snapshot = await fresh(tab);
  if (!snapshot.includes(topicDetail)) {
    throw new Error(`京东后台未搜索到话题${topic}`);
  }
  await dialog.getByText(topicDetail, { exact: true }).click();
  const selected = await fresh(tab);
  if (!selected.includes(topicDetail)) {
    throw new Error(`话题${topic}选择失败`);
  }
}

async function selectLabel(tab, labelType) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await fresh(tab);
      const comboboxes = tab.playwright.getByRole("combobox");
      if ((await comboboxes.count()) < 2) {
        throw new Error("没有找到京东标签类型选择器");
      }
      await comboboxes.nth(1).click();
      await tab.playwright.waitForTimeout(500);
      await fresh(tab);

      const style = tab.playwright.getByRole("menuitemcheckbox", {
        name: "体裁标签 right",
        exact: true,
      });
      if ((await style.count()) !== 1) {
        throw new Error("体裁标签菜单未打开");
      }
      await style.click();
      await tab.playwright.waitForTimeout(500);
      await fresh(tab);

      const review = tab.playwright.getByRole("menuitemcheckbox", {
        name: "测评体裁 right",
        exact: true,
      });
      if ((await review.count()) !== 1) {
        throw new Error("测评体裁菜单未打开");
      }
      await review.click();
      await tab.playwright.waitForTimeout(500);
      await fresh(tab);

      const selectedLabel = tab.playwright.getByRole("menuitemcheckbox", {
        name: labelType,
        exact: true,
      });
      if ((await selectedLabel.count()) !== 1) {
        throw new Error(`标签${labelType}选项未显示`);
      }
      await selectedLabel.click();
      const selected = await fresh(tab);
      if (!selected.includes(`generic "${labelType}"`)) {
        throw new Error(`标签${labelType}选择失败`);
      }
      return;
    } catch (error) {
      lastError = error;
      await tab.playwright.waitForTimeout(500);
    }
  }
  throw lastError;
}

function parseLocalSchedule(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(value);
  if (!match) {
    throw new Error("无法解析定时发布时间");
  }
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
  };
}

async function selectSchedule(tab, value) {
  const target = parseLocalSchedule(value);
  await fresh(tab);
  await tab.playwright
    .getByRole("radio", { name: "定时发布", exact: true })
    .click();
  await fresh(tab);
  const input = tab.playwright.locator('input[placeholder="请选择日期"]');
  await input.click();
  await fresh(tab);

  const dropdown = tab.playwright.locator(
    ".jd-picker-dropdown:not(.jd-picker-dropdown-hidden)",
  );
  if ((await dropdown.count()) !== 1) {
    throw new Error("京东定时发布日期选择器没有正常打开");
  }
  const yearText = await dropdown.locator(".jd-picker-year-btn").textContent();
  const monthText = await dropdown.locator(".jd-picker-month-btn").textContent();
  const currentYear = Number(String(yearText).replace(/\D/g, ""));
  const currentMonth = Number(String(monthText).replace(/\D/g, ""));
  const monthDelta =
    (target.year - currentYear) * 12 + (target.month - currentMonth);
  const navigation =
    monthDelta >= 0
      ? dropdown.locator(".jd-picker-header-next-btn")
      : dropdown.locator(".jd-picker-header-prev-btn");
  for (let index = 0; index < Math.abs(monthDelta); index += 1) {
    await navigation.click();
    await fresh(tab);
  }

  const dayCell = dropdown
    .locator(".jd-picker-cell-in-view:not(.jd-picker-cell-disabled)")
    .getByText(String(target.day), { exact: true });
  if ((await dayCell.count()) !== 1) {
    throw new Error(`无法在日期选择器中唯一定位${target.day}日`);
  }
  await dayCell.click();
  await fresh(tab);

  const columns = dropdown.locator(".jd-picker-time-panel-column");
  if ((await columns.count()) !== 2) {
    throw new Error("京东时间选择器结构发生变化");
  }
  const hour = String(target.hour).padStart(2, "0");
  const minute = String(target.minute).padStart(2, "0");
  await columns.nth(0).getByText(hour, { exact: true }).click();
  await fresh(tab);
  await columns.nth(1).getByText(minute, { exact: true }).click();
  await fresh(tab);
  await dropdown.getByRole("button", { name: "确定", exact: true }).click();
  await fresh(tab);

  const actual = await input.getAttribute("value");
  if (actual !== value) {
    throw new Error(`定时发布时间写入不一致：期望${value}，实际${actual || "空"}`);
  }
}

async function waitForPublishResult(tab, timeoutMs) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    await pause(1500);
    const snapshot = await fresh(tab);
    const currentUrl = await tab.url();
    if (currentUrl && currentUrl.includes("/n/content-list.html")) {
      return { ok: true, snapshot };
    }
    if (/发布成功|提交成功|已定时/.test(snapshot)) {
      return { ok: true, snapshot };
    }
    if (/发布失败|提交失败|请检查/.test(snapshot)) {
      throw new Error("京东后台提示发布失败，请查看当前页面");
    }
  }
  throw new Error(`提交发布后等待结果超过${Math.round(timeoutMs / 1000)}秒`);
}

export async function fillJdPublishForm(
  tab,
  job,
  {
    commit = false,
    uploadTimeoutMs = 20 * 60 * 1000,
    publishTimeoutMs = 2 * 60 * 1000,
  } = {},
) {
  assertJob(job);
  const currentUrl = await tab.url();
  if (currentUrl === JD_PUBLISH_URL) {
    await tab.reload();
  } else {
    await tab.goto(JD_PUBLISH_URL);
  }
  let initial = "";
  for (let index = 0; index < 15; index += 1) {
    await pause(500);
    initial = await fresh(tab);
    if (initial.includes("视频发布") && initial.includes("上传视频")) {
      break;
    }
  }
  if (!initial.includes("视频发布") || !initial.includes("上传视频")) {
    throw new Error("京东发布页面未正常打开，可能需要重新登录");
  }

  await uploadVideo(tab, job.video_path, uploadTimeoutMs);
  await selectCover(tab, job.cover_path);
  await fillTitle(tab, job.title);
  await selectProducts(tab, job.skus);
  await selectTopic(tab, job.topic);
  await selectLabel(tab, job.label_type);
  await selectSchedule(tab, job.scheduled_publish_time);

  const preSubmitSnapshot = await fresh(tab);
  for (const expected of [
    job.title,
    `${job.topic}详情`,
    job.label_type,
    job.scheduled_publish_time,
    'img "封面预览"',
  ]) {
    if (!preSubmitSnapshot.includes(expected)) {
      throw new Error(`发布前核对失败，页面缺少：${expected}`);
    }
  }
  const publishButton = tab.playwright.getByRole("button", {
    name: "发布",
    exact: true,
  });
  const disabled = await publishButton.getAttribute("disabled");
  const ariaDisabled = await publishButton.getAttribute("aria-disabled");
  if (disabled !== null || ariaDisabled === "true") {
    throw new Error("表单已填写，但京东发布按钮仍不可用");
  }
  if (!commit) {
    return {
      task_id: job.task_id,
      status: "dry_run_ready",
      committed: false,
    };
  }

  await publishButton.click();
  await waitForPublishResult(tab, publishTimeoutMs);
  return {
    task_id: job.task_id,
    status: "submitted",
    committed: true,
  };
}

export {
  fillTitle,
  selectCover,
  selectLabel,
  selectProducts,
  selectSchedule,
  selectTopic,
  uploadVideo,
};
