# frozen_string_literal: true

require 'fiddle/import'

# Native Windows-only cache reader. No Cygwin mode bits, pathname ACL checks,
# external commands, catalog deserialization or new gems establish trust here.
module NestCompilerWindowsCache
  REPORT = NestUpdateCatalogReport
  TRUSTED = ['S-1-5-18', 'S-1-5-32-544'].freeze
  WRITE_ACCESS = 0x500d0156 # Generic all/write, delete, DAC/owner and file writes.

  def self.api
    REPORT.require_value(RUBY_PLATFORM == 'x64-mingw32' && Fiddle::SIZEOF_VOIDP == 8)
    return @api if @api
    @api = Module.new do
      extend Fiddle::Importer
      dlload 'kernel32.dll', 'advapi32.dll', 'ntdll.dll'
      extern 'void* CreateFileW(void*, unsigned long, unsigned long, void*, unsigned long, unsigned long, void*)'
      extern 'int CloseHandle(void*)'
      extern 'unsigned long GetFileType(void*)'
      extern 'int GetFileInformationByHandle(void*, void*)'
      extern 'int ReadFile(void*, void*, unsigned long, void*, void*)'
      extern 'unsigned long GetSecurityInfo(void*, int, unsigned long, void*, void*, void*, void*, void*)'
      extern 'int GetAclInformation(void*, void*, unsigned long, int)'
      extern 'int GetAce(void*, unsigned long, void*)'
      extern 'int IsValidSid(void*)'
      extern 'unsigned long GetLengthSid(void*)'
      extern 'int ConvertSidToStringSidW(void*, void*)'
      extern 'void* LocalFree(void*)'
      extern 'void* GetCurrentProcess()'
      extern 'int OpenProcessToken(void*, unsigned long, void*)'
      extern 'int GetTokenInformation(void*, int, void*, unsigned long, void*)'
      extern 'long NtQuerySystemInformation(int, void*, unsigned long, void*)'
    end
  rescue Fiddle::DLError
    raise REPORT::Unavailable, 'Native cache API unavailable'
  end

  def self.pointer_slot
    Fiddle::Pointer["\0".b * Fiddle::SIZEOF_VOIDP]
  end

  def self.pointer(slot)
    Fiddle::Pointer.new(slot[0, Fiddle::SIZEOF_VOIDP].unpack1('J'))
  end

  def self.elevated?
    slot = pointer_slot
    REPORT.require_value(api.OpenProcessToken(api.GetCurrentProcess, 8, slot) != 0)
    handle = pointer(slot)
    begin
      value = "\0".b * 4
      REPORT.require_value(api.GetTokenInformation(handle, 20, value, 4, "\0".b * 4) != 0)
      value.unpack1('L<') == 1
    ensure
      api.CloseHandle(handle)
    end
  end

  def self.boot_id
    # SYSTEM_BOOT_ENVIRONMENT_INFORMATION begins with a native GUID. Serialize
    # its documented little-endian integer fields, not an inferred clock value.
    buffer = "\0".b * 32
    REPORT.require_value(api.NtQuerySystemInformation(90, buffer, buffer.bytesize, "\0".b * 4).zero?)
    values = buffer.unpack('L<S<S<C8')
    REPORT.require_value(values.any?(&:positive?))
    '%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x' % values
  end

  def self.sid(value)
    REPORT.require_value(!value.null? && api.IsValidSid(value) != 0)
    slot = pointer_slot
    REPORT.require_value(api.ConvertSidToStringSidW(value, slot) != 0)
    text = pointer(slot)
    begin
      # Windows SIDs have at most 15 subauthorities; bound even OS output.
      units = []
      256.times do |index|
        unit = text[index * 2, 2].unpack1('S<')
        return units.pack('S<*').force_encoding('UTF-16LE').encode('UTF-8') if unit.zero?
        units << unit
      end
      raise REPORT::Unavailable, 'SID unavailable'
    ensure
      api.LocalFree(text)
    end
  end

  def self.allowed_ace?(type, mask, trustee, directory: false)
    # Unknown/object/callback ACEs refuse instead of approximating their rights.
    # Creating new children in a directory cannot replace an existing protected
    # child. Still refuse delete-child, delete, DAC/owner and generic write/all.
    forbidden = directory ? (WRITE_ACCESS & ~0x116) : WRITE_ACCESS
    [0, 1].include?(type) && (type == 1 || mask.nobits?(forbidden) || TRUSTED.include?(trustee))
  end

  def self.check_acl(handle, directory: false)
    owner = pointer_slot
    acl = pointer_slot
    descriptor = pointer_slot
    REPORT.require_value(api.GetSecurityInfo(handle, 1, 5, owner, nil, acl, nil, descriptor).zero?)
    begin
      REPORT.require_value(TRUSTED.include?(sid(pointer(owner))))
      dacl = pointer(acl)
      REPORT.require_value(!dacl.null?) # A null DACL grants everybody access.
      info = "\0".b * 12
      REPORT.require_value(api.GetAclInformation(dacl, info, info.bytesize, 2) != 0)
      count, used, = info.unpack('L<3')
      REPORT.require_value(count <= 4096 && used <= 65_535)
      count.times do |index|
        slot = pointer_slot
        REPORT.require_value(api.GetAce(dacl, index, slot) != 0)
        ace = pointer(slot)
        type, flags, size, mask = ace[0, 8].unpack('CCS<L<')
        REPORT.require_value([0, 1].include?(type) && size >= 16 && size <= used)
        next unless flags.nobits?(8) # INHERIT_ONLY is not an effective grant.
        trustee = Fiddle::Pointer[ace[8, size - 8]]
        REPORT.require_value(api.IsValidSid(trustee) != 0 && api.GetLengthSid(trustee) <= size - 8)
        REPORT.require_value(allowed_ace?(type, mask, sid(trustee), directory: directory))
      end
    ensure
      api.LocalFree(pointer(descriptor))
    end
  end

  def self.open_handle(path)
    # OPEN_REPARSE_POINT prevents following the final component; every ancestor
    # is opened and held too. Share only reads, never writes or delete/rename.
    wide = (path + "\0").encode('UTF-16LE')
    handle = api.CreateFileW(wide, 0x80020000, 1, nil, 3, 0x02200000, nil)
    REPORT.require_value(!handle.null? && ![-1, (1 << 64) - 1].include?(handle.to_i))
    handle
  end

  def self.information(handle, directory:)
    info = "\0".b * 52
    REPORT.require_value(api.GetFileType(handle) == 1 && api.GetFileInformationByHandle(handle, info) != 0)
    attrs, = info.unpack('L<')
    REPORT.require_value(attrs.nobits?(0x400) && attrs.anybits?(0x10) == directory)
    REPORT.require_value(info[40, 4].unpack1('L<') == 1) unless directory
    info
  end

  def self.read_cache(path)
    # Puppet settings use drive-qualified paths. UNC/device paths, ADS, empty
    # components, dot traversal and trailing Windows-normalized names refuse.
    REPORT.require_value(path.is_a?(String) && %r{\A[A-Za-z]:/[^\\:\x00-\x1f]+\z}.match?(path))
    parts = path[3..].split('/', -1)
    REPORT.require_value(parts.all? { |part| !part.empty? && !part.end_with?('.', ' ') && !['.', '..'].include?(part) })
    handles = []
    begin
      # The drive root has normal user directory-creation rights; require its
      # native identity/no-reparse status, then ACL-check each named ancestor.
      handles << open_handle(path[0, 3])
      information(handles.last, directory: true)
      parts.each_index do |index|
        handle = open_handle(path[0, 3] + parts[0..index].join('/'))
        handles << handle
        directory = index < parts.length - 1
        information(handle, directory: directory)
        check_acl(handle, directory: directory)
      end
      handle = handles.last
      before = information(handle, directory: false)
      high, low = before[32, 8].unpack('L<2')
      size = (high << 32) | low
      REPORT.require_value(size <= REPORT::LIMIT)
      data = "\0".b * (size + 1)
      count = "\0".b * 4
      REPORT.require_value(api.ReadFile(handle, data, size + 1, count, nil) != 0 && count.unpack1('L<') == size)
      after = information(handle, directory: false)
      # Reading can advance native LastAccessTime; it is not a content write.
      REPORT.require_value(after[0, 12] == before[0, 12] && after[20, 32] == before[20, 32])
      check_acl(handle)
      data.byteslice(0, size)
    ensure
      handles.reverse_each { |opened| api.CloseHandle(opened) }
    end
  end
end
