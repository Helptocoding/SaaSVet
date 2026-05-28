import { BrowserRouter, Routes, Route } from "react-router-dom";
import Login from "./pages/login";
import Dashboard from "./pages/dashboard";
import PrivateRoute from "./routes/privateRoutes";
import Pets from "./pages/pets";
import PetDetail from "./pages/petDetail";
import Layout from "./components/Layout";
import { useAuth } from "./auth/authContext";
import { AuthProvider } from "./auth/authContext";
import Staff from "./pages/staff";
import Appointments from "./pages/appointments";
import MedicalRecords from "./pages/medicalRecords/index";
import Inventory from "./pages/inventory";
import Billing from "./pages/billing";
import Cash from "./pages/cash";
import Prescriptions from "./pages/prescriptions";
import Analytics from "./pages/analytics";
import Config from "./pages/config";
import CreateOrganization from "./pages/platform/createOrganization";
import ChangePassword from "./pages/changePassword";
import NotFound from "./pages/notFound";
import { Navigate, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import FeedbackButton from "./components/FeedbackButton";
import { ConfirmProvider } from "./components/ConfirmDialog";
import { Toaster } from "sonner";

const LoadingScreen = () => (
  <div style={{
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    height: "100vh",
    backgroundColor: "#f5f5f5"
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

function AppContent() {
  const { initializing, user } = useAuth();

  if (initializing) {
    return <LoadingScreen />;
  }

  const wrap = (Component) => (
    <PrivateRoute>
      <MustChangePasswordGate>
        <Layout>
          <ErrorBoundary>
            <Component />
          </ErrorBoundary>
        </Layout>
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

  return (
    <>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={wrap(Dashboard)} />
        <Route path="/pets" element={wrap(Pets)} />
        <Route path="/pets/:id" element={wrap(PetDetail)} />
        <Route path="/staff" element={wrap(Staff)} />
        <Route path="/appointments" element={wrap(Appointments)} />
        <Route path="/medical-records" element={<PrivateRoute><MustChangePasswordGate><ErrorBoundary><MedicalRecords /></ErrorBoundary></MustChangePasswordGate></PrivateRoute>} />
        <Route path="/inventory" element={wrap(Inventory)} />
        <Route path="/billing" element={wrap(Billing)} />
        <Route path="/cash" element={wrap(Cash)} />
        <Route path="/prescriptions" element={wrap(Prescriptions)} />
        <Route path="/analytics" element={wrap(Analytics)} />
        <Route path="/config" element={wrap(Config)} />
        <Route path="/platform/organizations/new" element={wrap(CreateOrganization)} />
        <Route path="/change-password" element={wrapNoGate(ChangePassword)} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      {user && <FeedbackButton />}
    </>
  );
}


function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ConfirmProvider>
          <ErrorBoundary>
            <AppContent />
          </ErrorBoundary>
        </ConfirmProvider>
        <Toaster richColors position="top-right" toastOptions={{ duration: 4000 }} visibleToasts={3} />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
