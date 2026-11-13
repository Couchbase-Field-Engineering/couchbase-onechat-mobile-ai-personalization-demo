import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { DataProvider } from '@/src/data/DataContext';
import { AuthProvider } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { DeviceFrame } from '@/src/ui/DeviceFrame';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <DataProvider>
          <DeviceFrame>
            <StatusBar style="light" />
            <Stack
              screenOptions={{
                headerStyle: { backgroundColor: theme.color.ink },
                headerTintColor: theme.color.onDark,
                headerTitleStyle: { fontWeight: '600' },
                contentStyle: { backgroundColor: theme.color.bg },
              }}
            >
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="login" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="order" options={{ title: 'Track your order', presentation: 'modal' }} />
              <Stack.Screen name="return" options={{ title: 'Return or exchange', presentation: 'modal' }} />
              <Stack.Screen name="consult" options={{ title: 'Workspace consultation', presentation: 'modal' }} />
              <Stack.Screen name="ticket" options={{ title: 'IT help desk', presentation: 'modal' }} />
              <Stack.Screen name="onboarding" options={{ title: 'Onboarding checklist', presentation: 'modal' }} />
              <Stack.Screen name="benefits" options={{ title: 'Benefits enrollment', presentation: 'modal' }} />
              <Stack.Screen name="timeoff" options={{ title: 'Request time off', presentation: 'modal' }} />
              <Stack.Screen name="confirm" options={{ title: 'Review & confirm', presentation: 'modal' }} />
            </Stack>
          </DeviceFrame>
        </DataProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
