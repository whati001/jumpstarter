import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from bleak.exc import BleakError

# Import the classes from your driver module
# Adjust the import path based on your actual module structure
from .driver import (
    AsyncBleConfig,
    AsyncBleWrapper,
    BleWriteNotifyStream,
    _ble_notify_handler,
)


@pytest.fixture
def ble_config():
    """Fixture for BLE configuration."""
    return AsyncBleConfig(
        address="AA:BB:CC:DD:EE:FF",
        service_uuid="12345678-1234-5678-1234-56789abcdef0",
        write_char_uuid="12345678-1234-5678-1234-56789abcdef1",
        notify_char_uuid="12345678-1234-5678-1234-56789abcdef2",
    )


@pytest.fixture
def mock_service(ble_config):
    """Fixture for mock BLE service."""
    service = Mock()
    service.uuid = ble_config.service_uuid

    # Create characteristics for write and notify
    write_char = Mock()
    write_char.uuid = ble_config.write_char_uuid

    notify_char = Mock()
    notify_char.uuid = ble_config.notify_char_uuid

    service.characteristics = [write_char, notify_char]
    return service


@pytest.fixture
def mock_bleak_client(mock_service):
    """Fixture for mocked BleakClient."""
    client = AsyncMock()
    client.is_connected = True
    client.services = [mock_service]
    client.write_gatt_char = AsyncMock()
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()
    client.disconnect = AsyncMock()

    # Mock the context manager behavior
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    return client


@pytest.fixture
def ble_driver(ble_config, mock_bleak_client):
    """Fixture for BLE driver instance."""
    driver = BleWriteNotifyStream(
        address=ble_config.address,
        service_uuid=ble_config.service_uuid,
        write_char_uuid=ble_config.write_char_uuid,
        notify_char_uuid=ble_config.notify_char_uuid,
    )
    # Mock the logger
    driver.logger = Mock()

    # Mock the context manager behavior
    driver.connect = AsyncMock(return_value=mock_bleak_client)
    return driver


class TestBleNotifyHandler:
    """Tests for the notification handler function."""

    def test_notify_handler_success(self):
        """Test that notify handler successfully queues data."""
        queue = asyncio.Queue(maxsize=10)
        sender = Mock()
        data = bytearray(b"test_data")

        _ble_notify_handler(sender, data, queue)

        assert queue.qsize() == 1
        assert queue.get_nowait() == data

    def test_notify_handler_queue_full(self, capsys):
        """Test that notify handler handles full queue gracefully."""
        queue = asyncio.Queue(maxsize=1)
        # put some data into the queue to fill it up
        queue.put_nowait(b"existing_data")

        sender = Mock()
        data = bytearray(b"test_data")

        _ble_notify_handler(sender, data, queue)

        stderr_captured = capsys.readouterr()
        assert "Warning: Data queue is full" in stderr_captured.out


class TestAsyncBleWrapper:
    """Tests for AsyncBleWrapper stream."""

    @pytest.mark.asyncio
    async def test_send(self, mock_bleak_client, ble_config):
        """Test sending data through the wrapper."""
        queue = asyncio.Queue()
        wrapper = AsyncBleWrapper(
            client=mock_bleak_client,
            config=ble_config,
            notify_queue=queue,
        )

        test_data = b"test_message"
        await wrapper.send(test_data)

        mock_bleak_client.write_gatt_char.assert_called_once_with(
            ble_config.write_char_uuid, test_data
        )

    @pytest.mark.asyncio
    async def test_receive(self, mock_bleak_client, ble_config):
        """Test receiving data from the queue."""
        queue = asyncio.Queue()
        test_data = b"received_data"
        await queue.put(test_data)

        wrapper = AsyncBleWrapper(
            client=mock_bleak_client,
            config=ble_config,
            notify_queue=queue,
        )

        received = await wrapper.receive()
        assert received == test_data

    @pytest.mark.asyncio
    async def test_aclose(self, mock_bleak_client, ble_config):
        """Test closing the wrapper disconnects the client."""
        queue = asyncio.Queue()
        wrapper = AsyncBleWrapper(
            client=mock_bleak_client,
            config=ble_config,
            notify_queue=queue,
        )

        await wrapper.aclose()
        mock_bleak_client.disconnect.assert_called_once()


class TestBleWriteNotifyStream:
    """Tests for BleWriteNotifyStream driver."""

    def test_client_class_method(self):
        """Test that client method returns correct client class."""
        client_class = BleWriteNotifyStream.client()
        assert client_class == "jumpstarter_driver_ble.client.BleWriteNotifyStreamClient"

    @pytest.mark.asyncio
    async def test_info(self, ble_driver, ble_config):
        """Test info method returns correct information."""
        info = await ble_driver.info()

        assert ble_config.address in info
        assert ble_config.service_uuid in info
        assert ble_config.write_char_uuid in info
        assert ble_config.notify_char_uuid in info

    @pytest.mark.asyncio
    async def test_check_characteristics_success(
        self, ble_driver, mock_bleak_client
    ):
        """Test successful characteristic check."""
        # Should not raise any exception
        await ble_driver._check_ble_characteristics(mock_bleak_client)

    @pytest.mark.asyncio
    async def test_check_characteristics_missing_service(
        self, ble_driver, mock_bleak_client
    ):
        """Test that missing service raises BleakError."""
        mock_bleak_client.services = []

        with pytest.raises(BleakError, match="Service UUID .* not found on device."):
            await ble_driver._check_ble_characteristics(mock_bleak_client)

    @pytest.mark.asyncio
    async def test_check_characteristics_missing_write_char(
        self, ble_driver, mock_bleak_client, mock_service, ble_config
    ):
        """Test that missing write characteristic raises BleakError."""
        # Remove write characteristic
        notify_char = Mock()
        notify_char.uuid = ble_config.notify_char_uuid
        mock_service.characteristics = [notify_char]

        with pytest.raises(BleakError, match="Write characteristic UUID .* not found on device."):
            await ble_driver._check_ble_characteristics(mock_bleak_client)

    @pytest.mark.asyncio
    async def test_check_characteristics_missing_notify_char(
        self, ble_driver, mock_bleak_client, mock_service, ble_config
    ):
        """Test that missing notify characteristic raises BleakError."""
        # Remove notify characteristic
        write_char = Mock()
        write_char.uuid = ble_config.write_char_uuid
        mock_service.characteristics = [write_char]

        with pytest.raises(BleakError, match="Notify characteristic UUID .* not found on device."):
            await ble_driver._check_ble_characteristics(mock_bleak_client)
