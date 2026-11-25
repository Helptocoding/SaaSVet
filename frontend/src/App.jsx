import { createBrowserRouter, RouterProvider, Outlet, Navigate, useLocation } from "react-router-dom";
import Login from "./pages/login";
import Dashboard from "./pages/dashboard";
import PrivateRoute from "./routes/privateRoutes";
import Pets from "./pages/pets";
import PetDetail from "./pages/petDetail";
import Layout from "./components/Layout";
import { useAuth } from "./auth/authContext";
import { AuthProvider } from "./auth/AuthProvider";
import { ActivationProvider } from "./hooks/ActivationProvider";
import Staff, { StaffMemberRedirect } from "./pages/staff";
import Appointments from "./pages/appointments";
import MedicalRecords from "./pages/medicalRecords/index";
import Inventory from "./pages/inventory";
import Billing from "./pages/billing";
import POS from "./pages/pos";
import Cash from "./pages/cash";
import Prescriptions from "./pages/prescriptions";
import Analytics from "./pages/analytics";
import Config from "./pages/config";
import Imports from "./pages/imports/index";
import Inbox from "./pages/inbox";
import CreateOrganization from "./pages/platform/createOrganization";
import ChangePassword from "./pages/changePassword";
import AcceptLegal from "./pages/acceptLegal";
import NotFound from "./pages/notFound";
import ErrorBoundary from "./components/ErrorBoundary";
import { ConfirmProvider } from "./components/ConfirmDialog";
import { Toaster } from "sonner";
import { SkeletonTheme } from "react-loading-skeleton";

const LoadingScreen = () => (
  <div style={{
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    height: "100vh",
    backgroundColor: "var(--c-bg)"
  }}>
    <p>Cargando...</p>
  </div>
);

function MustChangePasswordGate({ children }) {
  // Frontend mirror of the backend ``MustChangePasswordGate`` permission.
  // The backend is the authoritative gate — this only handles UX.
  const { user } = useAuth();
  const location = useLocation();
  if (user?.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return children;
}

function LegalAcceptanceGate({ children }) {
  // Frontend mirror del backend ``LegalAcceptanceGate`` (ADR p46). El backend es
  // el gate autoritativo; esto solo maneja la UX. Va DESPUÉS del must-change
  // (orden: credencial → legal) y bloquea ANTES del Layout/Dashboard.
  const { user } = useAuth();
  const location = useLocation();
  if (user?.legal_acceptance_required && location.pathname !== "/aceptar-terminos") {
    return <Navigate to="/aceptar-terminos" replace />;
  }
  return children;
}

const wrap = (Component) => (
  <PrivateRoute>
    <MustChangePasswordGate>
      <LegalAcceptanceGate>
        <Layout>
          <ErrorBoundary>
            <Component />
          </ErrorBoundary>
        </Layout>
      </LegalAcceptanceGate>
    </MustChangePasswordGate>
  </PrivateRoute>
);

// /change-password is reachable even while must_change_password=true,
// so it does NOT go through MustChangePasswordGate.
const wrapNoGate = (Component) => (
  <PrivateRoute>
    <Layout>
      <ErrorBoundary>
        <Component />
      </ErrorBoundary>
    </Layout>
  </PrivateRoute>
);

// Gate de inicialización + salida de las rutas hijas. Vive dentro de AuthProvider
// para acceder a `initializing`/`user`, y renderiza <Outlet/> del data router.
function AuthGate() {
  const { initializing } = useAuth();
  if (initializing) {
    return <LoadingScreen />;
  }
  // «Reportar un problema» vive en la barra superior (Layout y DashboardTopBar).
  return <Outlet />;
}

// Root layout route: providers dentro del data router (createBrowserRouter), de
// modo que useBlocker (guard de la consulta) y los hooks de navegación funcionen.
function Root() {
  return (
    <AuthProvider>
      <ActivationProvider>
        <ConfirmProvider>
          {/* Esqueletos de carga con los tokens del sistema. La animación se apaga
              sola con prefers-reduced-motion (CSS de la librería). */}
          <SkeletonTheme baseColor="var(--c-subtle)" highlightColor="var(--c-surface-2)">
            <ErrorBoundary>
              <AuthGate />
            </ErrorBoundary>
          </SkeletonTheme>
          <Toaster richColors position="top-right" toastOptions={{ duration: 4000 }} visibleToasts={3} />
        </ConfirmProvider>
      </ActivationProvider>
    </AuthProvider>
  );
}

const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: "/login", element: <Login /> },
      { path: "/", element: wrap(Dashboard) },
      { path: "/pets", element: wrap(Pets) },
      { path: "/pets/:id", element: wrap(PetDetail) },
      { path: "/staff", element: wrap(Staff) },
      // ADR p67 → rediseño 2026-11-25: la ficha es un panel lateral sobre Equipo.
      { path: "/staff/:publicId", element: wrap(StaffMemberRedirect) },
      { path: "/appointments", element: wrap(Appointments) },
      {
        path: "/medical-records",
        element: (
          <PrivateRoute>
            <MustChangePasswordGate>
              <LegalAcceptanceGate>
                <ErrorBoundary>
                  <MedicalRecords />
                </ErrorBoundary>
              </LegalAcceptanceGate>
            </MustChangePasswordGate>
          </PrivateRoute>
        ),
      },
      { path: "/inventory", element: wrap(Inventory) },
      { path: "/billing", element: wrap(Billing) },
      { path: "/pos", element: wrap(POS) },
      { path: "/cash", element: wrap(Cash) },
      { path: "/prescriptions", element: wrap(Prescriptions) },
      { path: "/inbox", element: wrap(Inbox) },
      { path: "/analytics", element: wrap(Analytics) },
      { path: "/config", element: wrap(Config) },
      { path: "/imports", element: wrap(Imports) },
      { path: "/platform/organizations/new", element: wrap(CreateOrganization) },
      { path: "/change-password", element: wrapNoGate(ChangePassword) },
      {
        path: "/aceptar-terminos",
        element: (
          <PrivateRoute>
            <MustChangePasswordGate>
              <ErrorBoundary>
                <AcceptLegal />
              </ErrorBoundary>
            </MustChangePasswordGate>
          </PrivateRoute>
        ),
      },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

function App() {
  return <RouterProvider router={router} />;
}

export default App;
