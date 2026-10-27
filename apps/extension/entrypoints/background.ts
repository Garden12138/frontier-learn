import { browser } from 'wxt/browser';
import { defineBackground } from 'wxt/utils/define-background';

export default defineBackground(() => {
  // Chrome skips activeTab grants for its automatic side-panel action. A normal action
  // receives the temporary grant before this listener opens the panel; it reads no DOM.
  browser.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});
  browser.action.onClicked.addListener(tab => {
    if (tab.windowId !== undefined) void browser.sidePanel.open({ windowId: tab.windowId }).catch(() => {});
  });
});
