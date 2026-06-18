/**
 * app.js — 入口文件（仅初始化）
 * 所有业务逻辑已拆分到 js/ 目录下的模块中
 * 加载顺序：state → utils → fileUpload → conversationManager → messageRenderer → uiManager → app
 */

document.addEventListener('DOMContentLoaded', init);
