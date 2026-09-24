import React from 'react';
import { TextInput } from 'react-native';
import TestRenderer, { act } from 'react-test-renderer';
import AsyncStorage from '@react-native-async-storage/async-storage';

import App from '../App';
import { WebAppScreen } from '../src/WebAppScreen';
import { WebsiteEntryScreen } from '../src/WebsiteEntryScreen';
import { saveWebsiteUrl } from '../src/websiteStorage';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

jest.mock('react-native-safe-area-context', () => {
  const { View } = require('react-native');
  return { SafeAreaProvider: View, SafeAreaView: View };
});
jest.mock('../src/WebAppScreen', () => ({ WebAppScreen: () => null }));

describe('website entry flow', () => {
  let renderer: TestRenderer.ReactTestRenderer;

  beforeEach(async () => {
    await AsyncStorage.clear();
    jest.clearAllMocks();
    await act(async () => {
      renderer = TestRenderer.create(<App />);
    });
  });

  afterEach(async () => {
    await act(async () => {
      renderer.unmount();
    });
    jest.restoreAllMocks();
  });

  it('does not load a fixed website before the user enters one', () => {
    expect(renderer.root.findAllByType(WebAppScreen)).toHaveLength(0);
    expect(renderer.root.findByType(TextInput).props.value).toBe('');
  });

  it('keeps invalid input on the form', async () => {
    const scriptUrl = ['java', 'script:1'].join('');
    await act(async () => {
      renderer.root.findByType(TextInput).props.onChangeText(scriptUrl);
    });
    await act(async () => {
      renderer.root.findByType(TextInput).props.onSubmitEditing();
    });
    expect(renderer.root.findAllByType(WebAppScreen)).toHaveLength(0);
    expect(renderer.root.findByType(TextInput).props.value).toBe(scriptUrl);
    expect(AsyncStorage.setItem).not.toHaveBeenCalled();
  });

  it('opens the full server URL and allows switching to another website', async () => {
    await act(async () => {
      renderer.root
        .findByType(TextInput)
        .props.onChangeText('server.example.com/app?id=42');
    });
    await act(async () => {
      renderer.root.findByType(TextInput).props.onSubmitEditing();
    });
    expect(renderer.root.findByType(WebAppScreen).props.startUrl).toBe(
      'https://server.example.com/app?id=42',
    );
    await act(async () => {
      renderer.root.findByType(WebAppScreen).props.onClose();
    });
    expect(renderer.root.findByType(WebsiteEntryScreen).props.initialUrl).toBe(
      'https://server.example.com/app?id=42',
    );
    await act(async () => {
      renderer.root
        .findByType(TextInput)
        .props.onChangeText('http://192.168.1.20:3030/');
    });
    await act(async () => {
      renderer.root.findByType(TextInput).props.onSubmitEditing();
    });
    expect(renderer.root.findByType(WebAppScreen).props.startUrl).toBe(
      'http://192.168.1.20:3030/',
    );
    await act(async () => {
      renderer.unmount();
    });
    await act(async () => {
      renderer = TestRenderer.create(<App />);
    });
    expect(renderer.root.findByType(WebAppScreen).props.startUrl).toBe(
      'http://192.168.1.20:3030/',
    );
  });

  it('automatically reopens the saved URL including path and query after restart', async () => {
    await act(async () => {
      renderer.unmount();
    });
    await saveWebsiteUrl('https://example.com/apps?entry=mobile#home');
    await act(async () => {
      renderer = TestRenderer.create(<App />);
    });
    expect(renderer.root.findAllByType(WebsiteEntryScreen)).toHaveLength(0);
    expect(renderer.root.findByType(WebAppScreen).props.startUrl).toBe(
      'https://example.com/apps?entry=mobile#home',
    );
  });

  it('waits for storage before showing either the entry page or the website', async () => {
    await act(async () => {
      renderer.unmount();
    });
    let finishLoad!: (url: string | null) => void;
    jest.spyOn(AsyncStorage, 'getItem').mockImplementationOnce(
      () =>
        new Promise(resolve => {
          finishLoad = resolve;
        }),
    );
    await act(async () => {
      renderer = TestRenderer.create(<App />);
    });
    expect(renderer.root.findAllByType(WebsiteEntryScreen)).toHaveLength(0);
    expect(renderer.root.findAllByType(WebAppScreen)).toHaveLength(0);
    await act(async () => {
      finishLoad('https://example.com/');
    });
    expect(renderer.root.findByType(WebAppScreen).props.startUrl).toBe(
      'https://example.com/',
    );
  });

  it('allows input again if reading storage fails', async () => {
    await act(async () => {
      renderer.unmount();
    });
    jest
      .spyOn(AsyncStorage, 'getItem')
      .mockRejectedValueOnce(new Error('read failed'));
    await act(async () => {
      renderer = TestRenderer.create(<App />);
    });
    expect(renderer.root.findByType(TextInput).props.value).toBe('');
    expect(
      renderer.root.findByType(WebsiteEntryScreen).props.initialError,
    ).toContain('请重新输入');
  });

  it('keeps the address available for retry when saving fails', async () => {
    jest
      .spyOn(AsyncStorage, 'setItem')
      .mockRejectedValueOnce(new Error('write failed'));
    await act(async () => {
      renderer.root.findByType(TextInput).props.onChangeText('example.com');
    });
    await act(async () => {
      await renderer.root.findByType(TextInput).props.onSubmitEditing();
    });
    expect(renderer.root.findAllByType(WebAppScreen)).toHaveLength(0);
    expect(renderer.root.findByType(TextInput).props.value).toBe('example.com');
    expect(renderer.root.findByType(TextInput).props.editable).toBe(true);
    await act(async () => {
      await renderer.root.findByType(TextInput).props.onSubmitEditing();
    });
    expect(renderer.root.findByType(WebAppScreen).props.startUrl).toBe(
      'https://example.com/',
    );
  });

  it('restores server history and connects directly from a history entry', async () => {
    await act(async () => renderer.unmount());
    await saveWebsiteUrl('https://first.example.com/');
    await saveWebsiteUrl('http://192.168.1.20:3030/');
    await act(async () => {
      renderer = TestRenderer.create(<App />);
    });
    await act(async () =>
      renderer.root.findByType(WebAppScreen).props.onClose(),
    );
    expect(renderer.root.findByType(WebsiteEntryScreen).props.history).toEqual([
      'http://192.168.1.20:3030/',
      'https://first.example.com/',
    ]);
    await act(async () => {
      await renderer.root
        .findAll(node => typeof node.props.onPress === 'function')
        .find(
          button =>
            button.props.accessibilityLabel ===
            '连接历史服务器：https://first.example.com/',
        )!
        .props.onPress();
    });
    expect(renderer.root.findByType(WebAppScreen).props.startUrl).toBe(
      'https://first.example.com/',
    );
    await act(async () =>
      renderer.root.findByType(WebAppScreen).props.onClose(),
    );
    expect(renderer.root.findByType(WebsiteEntryScreen).props.history[0]).toBe(
      'https://first.example.com/',
    );
  });
});
