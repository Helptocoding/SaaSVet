# B9E — campaña WSL2 de 1947726, 11-10-2026

Decisión: **PENDING / PREFLIGHT_BLOCKED**. [Reporte](REPORT.md).

Se preparó el candidato exacto en Linux y pasó la instalación congelada del frontend.
El controlador falló antes del sellado al importar Django sin cargar SECRET_KEY.
El controlador usado se conserva intacto. `launch_campaign.py` corrige el arranque;
solo se ejecutó con `--validate-only`, sin tests ni reinicio de campaña.

La instancia privada, su base vacía y la carpeta temporal se retiraron. Se conserva
la campaña Windows previa byte por byte. Todos los bloques de aplicación y PROFILE
permanecen NOT_EXECUTED. El plan conserva una sola ejecución formal por bloque.

Los helpers de ejecución posteriores al preflight no llegaron a ejecutarse y no
se presentan como validados de extremo a extremo. Los logs originales se conservan
en el paquete, con inventario de hashes y recuperación comprobada. Sin commit/push.
