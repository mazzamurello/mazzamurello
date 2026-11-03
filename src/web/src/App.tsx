import { Navigate, Route, Routes } from "react-router";

import { ConversationView } from "./components/ConversationView";
import { ModelSettings } from "./components/ModelSettings";
import { Shell } from "./components/Shell";
import { SignIn } from "./components/SignIn";
import { Welcome } from "./components/Welcome";
import { useMe } from "./session";

export function App() {
  const me = useMe();
  if (me === undefined) return null;
  if (me === null) return <SignIn />;
  return (
    <Routes>
      <Route element={<Shell me={me} />}>
        <Route index element={<Welcome />} />
        <Route path="c/:conversationId" element={<ConversationView />} />
        <Route path="settings/models" element={<ModelSettings me={me} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
