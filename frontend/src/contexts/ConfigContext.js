import React, { createContext, useContext, useState, useEffect } from 'react';

const ConfigContext = createContext();

export const useConfig = () => {
  const context = useContext(ConfigContext);
  if (!context) {
    throw new Error('useConfig must be used within ConfigProvider');
  }
  return context;
};

export const ConfigProvider = ({ children }) => {
  const [config, setConfig] = useState({
    minPasswordLength: 8, // Default fallback
    loaded: false,
  });

  const apiUrl = process.env.REACT_APP_API_URL || '/api';

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await fetch(`${apiUrl}/system/config/`);
        if (response.ok) {
          const data = await response.json();
          setConfig({
            minPasswordLength: data.settings?.min_password_length || 8,
            features: data.features || {},
            loaded: true,
          });
        } else {
          // Use defaults if fetch fails
          setConfig(prev => ({ ...prev, loaded: true }));
        }
      } catch (error) {
        console.error('Error fetching system config:', error);
        // Use defaults if fetch fails
        setConfig(prev => ({ ...prev, loaded: true }));
      }
    };

    fetchConfig();
  }, [apiUrl]);

  return (
    <ConfigContext.Provider value={config}>
      {children}
    </ConfigContext.Provider>
  );
};
