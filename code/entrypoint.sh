#!/Bin/bash
set -e

# 1. Handle .netrc permission issues and be compatible with different container users
if [ -f "/tmp/host_netrc" ]; then
    echo "🔑 Configure NASA credentials..."
    set -- /root/.netrc "$HOME/.netrc"
    # If there are other common user home directories, try to copy them too (for example, isce user)
    if [ -d "/home/isce" ]; then
        set -- "$@" /home/isce/.netrc
    fi

    for dest in "$@"; do
        destdir=$(dirname "$dest")
        if [ ! -d "$destdir" ]; then
            mkdir -p "$destdir" || true
        fi
        if cp /tmp/host_netrc "$dest" 2>/dev/null; then
            chmod 600 "$dest" 2>/dev/null || true
            # If currently root, try to attribute the file to the target user (if the target is not /root)
            if [ "$(id -u)" -eq 0 ]; then
                if [ "$dest" != "/root/.netrc" ]; then
                    user=$(stat -c '%U' "$destdir" 2>/dev/null || echo root)
                    if [ "$user" != "root" ]; then
                        chown "$user":"$user" "$dest" 2>/dev/null || true
                    fi
                fi
            fi
            echo "   -> Copied to $dest (Permissions: $(ls -l $dest))"
        else
            echo "   ⚠️ Unable to copy to $dest (possibly insufficient permissions)"
        fi
    done
else
    echo "⚠️ Credentials for mount /tmp/host_netrc not found, rail download may fail!"
fi

# 2. Execute the incoming command (i.e. python code/main_parallel.py)
exec "$@"