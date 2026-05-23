import React from "react";
import ReactDOM from "react-dom/client";
import { ClerkProvider } from '@clerk/clerk-react';
import App from "./App";

const clerkPubKey = process.env.REACT_APP_CLERK_PUBLISHABLE_KEY;

const root = ReactDOM.createRoot(document.getElementById("root"));

// Conditionally wrap with ClerkProvider only if Clerk is configured
if (clerkPubKey) {
  console.log('✓ Clerk authentication enabled');
  root.render(
    <ClerkProvider publishableKey={clerkPubKey}>
      <App />
    </ClerkProvider>
  );
} else {
  console.log('ℹ️ Clerk authentication not configured. Using Django default authentication.');
  root.render(<App />);
}
