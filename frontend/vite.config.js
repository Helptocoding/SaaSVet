/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// P1-5 A4: source maps subidos a Sentry — no aceptar stack traces minificados
// en beta. El plugin SOLO se carga cuando las credenciales de upload están
// presentes (build de prod en CI), así dev/test no necesitan el token ni que el
// paquete esté instalado. El token vive únicamente en CI/build, NUNCA en el bundle.
export default defineConfig(async () => {
  const plugins = [react()]

  const { SENTRY_AUTH_TOKEN, SENTRY_ORG, SENTRY_PROJECT, VITE_SENTRY_RELEASE } = process.env
  if (SENTRY_AUTH_TOKEN && SENTRY_ORG && SENTRY_PROJECT) {
    const { sentryVitePlugin } = await import('@sentry/vite-plugin')
    plugins.push(
      sentryVitePlugin({
        org: SENTRY_ORG,
        project: SENTRY_PROJECT,
        authToken: SENTRY_AUTH_TOKEN,
        release: { name: VITE_SENTRY_RELEASE || undefined },
        sourcemaps: {
          // Subir y luego BORRAR los .map del dist → nunca se sirven al público.
          filesToDeleteAfterUpload: ['./dist/**/*.map'],
        },
      })
    )
  }

  return {
    plugins,
    // 'hidden': emite los .map sin el comentario sourceMappingURL (el navegador
    // no los descarga). En prod el plugin los sube y borra; sin token, el
    // safeguard del Dockerfile (`find dist -name '*.map' -delete`) los elimina
    // antes de que nginx los pueda servir.
    build: { sourcemap: 'hidden' },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.js'],
      css: false,
    },
  }
})
