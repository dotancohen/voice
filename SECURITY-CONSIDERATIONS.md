### Security Considerations

1. **Use HTTPS**: The sync protocol does not encrypt data. Always use a reverse proxy with SSL for production.

2. **Restrict access**: Consider limiting access by IP if your devices have static IPs:
   ```nginx
   location / {
       allow 192.168.1.0/24;
       allow 203.0.113.50;
       deny all;
       proxy_pass http://127.0.0.1:8384;
   }
   ```

3. **Firewall defaults**: Block all incoming traffic except SSH and your sync port:
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow ssh
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

4. **Bind to localhost**: When using a reverse proxy, bind the sync server to localhost only:
   ```bash
   python -m src.main cli sync serve --host 127.0.0.1 --port 8384
   ```

5. **No CDN needed**: The sync server handles small JSON payloads between trusted devices. CDNs are not applicable.

