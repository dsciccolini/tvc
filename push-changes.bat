@echo off
echo Pushing changes to GitHub...
git add .
git commit -m "Update %date% %time%"
git push
echo Done!
pause