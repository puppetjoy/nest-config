require 'spec_helper'
require_relative '../../tasks/compiler_catalog_cache'
require_relative '../../tasks/compiler_windows_cache'

RSpec.describe NestCompilerWindowsCache do
  # Fiddle creates the native DLL methods at runtime; no Ruby class defines them.
  let(:api) { double('Native Win32 functions') } # rubocop:disable RSpec/VerifiedDoubles
  let(:handle) { Fiddle::Pointer.new(123) }

  before :each do
    allow(described_class).to receive(:api).and_return(api)
  end

  def information(attributes: 0, links: 1)
    # Valid UTF-8 multibyte sequences inside native timestamps used to shift
    # String character offsets. Native buffers must remain binary throughout.
    bytes = "\0".b * 52
    bytes[0, 4] = [attributes].pack('L<')
    bytes[4, 4] = "\xc2\xa9\xc2\xa9".b
    bytes[40, 4] = [links].pack('L<')
    bytes
  end

  def native_info(bytes)
    allow(api).to receive(:GetFileType).with(handle).and_return(1)
    allow(api).to receive(:GetFileInformationByHandle) do |_handle, buffer|
      expect(buffer.encoding).to eq(Encoding::BINARY)
      buffer.replace(bytes)
      1
    end
  end

  it 'accepts native SYSTEM/Administrators writes and unprivileged reads only' do
    ['S-1-5-18', 'S-1-5-32-544'].each do |sid|
      expect(described_class.allowed_ace?(0, 0x1f01ff, sid)).to be(true)
    end
    expect(described_class.allowed_ace?(0, 0x120089, 'S-1-1-0')).to be(true)
    expect(described_class.allowed_ace?(1, 0x1f01ff, 'S-1-1-0')).to be(true)
    [2, 4, 16, 64, 256, 0x10000, 0x40000, 0x80000, 0x40000000, 0x10000000].each do |right|
      expect(described_class.allowed_ace?(0, right, 'S-1-1-0')).to be(false)
    end
    [2, 5, 9, 11, 17].each do |type|
      expect(described_class.allowed_ace?(type, 0, 'S-1-5-18')).to be(false)
    end
  end

  it 'permits directory creation but never replacement or ACL takeover by another principal' do
    expect(described_class.allowed_ace?(0, 0x116, 'S-1-1-0', directory: true)).to be(true)
    [64, 0x10000, 0x40000, 0x80000, 0x40000000, 0x10000000].each do |right|
      expect(described_class.allowed_ace?(0, right, 'S-1-1-0', directory: true)).to be(false)
    end
  end

  it 'reads native metadata by byte offset regardless of timestamp UTF-8 sequences' do
    bytes = information
    native_info(bytes)
    expect(described_class.information(handle, directory: false)).to eq(bytes)
    expect(described_class.pointer_slot[0, Fiddle::SIZEOF_VOIDP]).to eq("\0".b * Fiddle::SIZEOF_VOIDP)
  end

  it 'rejects reparse points, directories, multiple hardlinks and non-disk handles' do
    [information(attributes: 0x400), information(attributes: 0x10), information(links: 2)].each do |bytes|
      native_info(bytes)
      expect { described_class.information(handle, directory: false) }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
    native_info(information)
    allow(api).to receive(:GetFileType).and_return(3)
    expect { described_class.information(handle, directory: false) }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'holds native read-only handles with no write/delete sharing or reparse following' do
    expect(api).to receive(:CreateFileW) do |wide, access, sharing, security, disposition, flags, template|
      expect(wide.encode('UTF-8')).to eq("C:/fixture\0")
      expect([access, sharing, security, disposition, flags, template]).to eq([0x80020000, 1, nil, 3, 0x02200000, nil])
      handle
    end
    expect(described_class.open_handle('C:/fixture')).to eq(handle)
  end

  it 'rejects invalid open handles and all noncanonical device, stream or traversal paths before opening' do
    allow(api).to receive(:CreateFileW).and_return(Fiddle::Pointer.new((1 << 64) - 1))
    expect { described_class.open_handle('C:/fixture') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    expect(api).not_to receive(:CreateFileW)
    ['relative', '//server/share/file', '//?/C:/file', 'C:/a:stream', 'C:/a/../file', 'C:/a//file', 'C:/a./file', 'C:/a /file', "C:/a\0file"].each do |path|
      expect { described_class.read_cache(path) }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
  end

  it 'bounds the native read, tolerates read access-time changes and closes every held handle on failure' do
    root = Fiddle::Pointer.new(124)
    bytes = information
    bytes[36, 4] = [3].pack('L<')
    after = bytes.dup
    after[12, 8] = [17].pack('Q<')
    allow(described_class).to receive(:open_handle).with('C:/').and_return(root)
    allow(described_class).to receive(:open_handle).with('C:/cache.json').and_return(handle)
    allow(described_class).to receive(:information).with(root, directory: true).and_return(information(attributes: 16))
    allow(described_class).to receive(:information).with(handle, directory: false).and_return(bytes, bytes, after)
    allow(described_class).to receive(:check_acl).with(handle, directory: false)
    allow(described_class).to receive(:check_acl).with(handle)
    allow(api).to receive(:ReadFile) do |opened, data, bound, count, overlap|
      expect([opened, bound, overlap]).to eq([handle, 4, nil])
      expect(data.encoding).to eq(Encoding::BINARY)
      data[0, 3] = 'abc'
      count.replace([3].pack('L<'))
      1
    end
    expect(api).to receive(:CloseHandle).with(handle).twice
    expect(api).to receive(:CloseHandle).with(root).twice
    expect(described_class.read_cache('C:/cache.json')).to eq('abc')
    allow(api).to receive(:ReadFile).and_return(0)
    expect { described_class.read_cache('C:/cache.json') }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'requires an elevated native token and closes its handle even on API failure' do
    allow(api).to receive_messages(GetCurrentProcess: handle, GetTokenInformation: 0)
    allow(api).to receive(:OpenProcessToken) do |_process, _access, slot|
      slot[0, Fiddle::SIZEOF_VOIDP] = [handle.to_i].pack('J')
      1
    end
    allow(api).to receive(:GetTokenInformation) do |_token, kind, value, _size, _returned|
      expect(kind).to eq(20)
      value.replace([1].pack('L<'))
      1
    end
    expect(api).to receive(:CloseHandle).with(handle).twice
    expect(described_class.elevated?).to be(true)
    allow(api).to receive_messages(GetCurrentProcess: handle, GetTokenInformation: 0)
    expect { described_class.elevated? }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'serializes the exact native boot GUID and refuses a zero or unavailable boot identity' do
    allow(api).to receive(:NtQuerySystemInformation) do |kind, value, size, _returned|
      expect([kind, size]).to eq([90, 32])
      value[0, 16] = [0x250d65c6, 0x2260, 0x11f1, 0xb0, 0xfe, 0xb4, 0xe9, 0x6c, 0xea, 0x63, 0x27].pack('L<S<S<C8')
      0
    end
    expect(described_class.boot_id).to eq('250d65c6-2260-11f1-b0fe-b4e96cea6327')
    allow(api).to receive(:NtQuerySystemInformation).and_return(0)
    expect { described_class.boot_id }.to raise_error(NestUpdateCatalogReport::Unavailable)
    allow(api).to receive(:NtQuerySystemInformation).and_return(-1)
    expect { described_class.boot_id }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end
end
