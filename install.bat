@echo off
title FETCH - Kurulum

echo.
echo  ================================
echo   FETCH - Bagimlilik Kurulumu
echo  ================================
echo.

:: Python kontrolu (python ve py her ikisi de denenir)
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [HATA] Python bulunamadi! Lutfen Python 3.x yukleyin.
        echo  https://www.python.org/downloads/
        echo.
        echo  Indirme sayfasi aciliyor...
        cmd /c start "" "https://www.python.org/downloads/"
        pause
        exit /b 1
    ) else (
        set PYCMD=py
    )
) else (
    set PYCMD=python
)

%PYCMD% --version
echo [OK] Python bulundu.
echo.
echo Bagimliliklar yukleniyor...
echo.

%PYCMD% -m pip install flask
%PYCMD% -m pip install pyngrok
%PYCMD% -m pip install pystray
%PYCMD% -m pip install Pillow

echo.

:: Ngrok authtoken kurulumu
echo  --------------------------------
echo   Ngrok Authtoken Kurulumu
echo  --------------------------------
echo.
echo  Tarayici aciliyor, hesap olusturup authtoken'ini kopyala...
echo.
cmd /c start "" "https://dashboard.ngrok.com/get-started/your-authtoken"
timeout /t 3 /nobreak >nul
set NGROK_TOKEN=
set /p NGROK_TOKEN=" Authtoken'ini buraya yapistir: "

if "%NGROK_TOKEN%"=="" (
    echo [ATLANDI] Token girilmedi. Daha sonra elle ayarlayabilirsin:
    echo   ngrok config add-authtoken TOKEN_BURAYA
    goto :done
)

ngrok config add-authtoken %NGROK_TOKEN%
echo [OK] Authtoken kaydedildi.

:done

echo.
echo  ================================
echo   Kurulum tamamlandi!
echo  ================================
echo.
echo FETCH'i baslatmak icin: py tray.py
echo.
pause
