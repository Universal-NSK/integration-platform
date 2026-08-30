$env:NASHDOM_BROWSER_PATH = "C:\ProgramData\Universal\IntegrationPlatform\drivers\chrome\chrome-win\chrome.exe"
$env:NASHDOM_DRIVER_PATH = "C:\ProgramData\Universal\IntegrationPlatform\drivers\chrome\chromedriver_win32\chromedriver.exe"
$env:NASHDOM_RUN_BROWSER_TEST = "1"

uv run pytest -m browser -vv -s