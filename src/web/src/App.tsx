import { Navigate, Route, Routes } from "react-router";

import { ConversationView } from "./components/ConversationView";
import { Settings } from "./components/Settings";
import { Shell } from "./components/Shell";
import { SignIn } from "./components/SignIn";
import { Welcome } from "./components/Welcome";
import { NoticeProvider } from "./notices";
import { useMe } from "./session";

export function App() {
  const me = useMe();
  if (me === undefined) return null;
  return (
    <NoticeProvider>
      {me === null ? (
        <SignIn />
      ) : (
        <Routes>
          <Route element={<Shell me={me} />}>
            <Route index element={<Welcome me={me} />} />
            <Route path="c/:conversationId" element={<ConversationView />} />
            <Route path="settings" element={<Settings me={me} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      )}
    </NoticeProvider>
  );
}
