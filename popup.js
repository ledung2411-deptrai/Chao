const btn = document.getElementById('toggleBtn');
const statusText = document.getElementById('status-text');

// Load trạng thái cũ
chrome.storage.local.get(['hadesEnabled'], (res) => {
    let isEnabled = res.hadesEnabled !== false;
    updateUI(isEnabled);
});

btn.onclick = () => {
    chrome.storage.local.get(['hadesEnabled'], (res) => {
        let newState = !(res.hadesEnabled !== false);
        chrome.storage.local.set({hadesEnabled: newState}, () => {
            updateUI(newState);
            // Reload tab để áp dụng thay đổi ngay
            chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
                if (tabs[0]) chrome.tabs.reload(tabs[0].id);
            });
        });
    });
};

function updateUI(isEnabled) {
    statusText.innerText = isEnabled ? "ON" : "OFF";
    statusText.className = isEnabled ? "on" : "off";
}
